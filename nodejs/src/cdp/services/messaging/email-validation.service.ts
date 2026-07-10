import { MxRecord } from 'node:dns'
import { Resolver } from 'node:dns/promises'
import { domainToASCII } from 'node:url'
import { Counter } from 'prom-client'

import { HogFlowAction } from '~/cdp/schema/hogflow'
import { RedisV2 } from '~/common/redis/redis-v2'

import { CyclotronJobInvocationHogFunction } from '../../types'

const cdpEmailMxValidationTotal = new Counter({
    name: 'cdp_email_mx_validation_total',
    help: 'Pre-send email validation outcomes. `invalid_syntax`/`invalid_domain` are predicted hard bounces; `transient_error` means DNS was unreliable so we allowed the send (fail-open); `hit_*` are cache hits.',
    labelNames: ['result'],
})

const cdpEmailMxSkippedTotal = new Counter({
    name: 'cdp_email_mx_skipped_total',
    help: 'Sends skipped by pre-send email validation as predicted hard bounces, per team.',
    labelNames: ['team_id', 'reason'],
})

// Deliberately conservative structural check — NOT full RFC 5322. It rejects
// obviously-malformed addresses (missing `@`, whitespace, no domain dot) while
// never rejecting an address that could actually deliver.
const EMAIL_SYNTAX_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

// Valid domains change rarely, so cache the "has mail servers" verdict for a day.
// Negative verdicts get a shorter TTL so a domain that comes back online recovers
// without a full day of blocked sends.
const POSITIVE_TTL_MS = 24 * 60 * 60 * 1000
const NEGATIVE_TTL_MS = 6 * 60 * 60 * 1000

// Local-only backoff after a transient DNS failure. Short enough that a real
// verdict is retried quickly, long enough that a resolver outage during a big
// batch doesn't repeat a 3s-timeout lookup for every send to the same domain.
// Never written to Valkey, so a blip on one worker isn't frozen fleet-wide.
const TRANSIENT_BACKOFF_MS = 60 * 1000

// Bound per-lookup latency: the email worker must not stall on a slow resolver.
const DNS_TIMEOUT_MS = 3000
const DNS_TRIES = 1

// Bounds worker memory against lists full of unique garbage domains; evicted
// domains just fall back to Valkey/DNS on their next send. ~150 B per entry,
// so this caps the cache at roughly 15 MB per worker.
export const MAX_LOCAL_CACHE_DOMAINS = 100_000

// Same key style as the SES rate limiter's '@posthog/ses/global' on the shared Valkey.
const VALKEY_KEY_PREFIX = '@posthog/ses/email-mx/'

type CacheEntry = { deliverable: boolean; transient?: boolean; expiresAt: number }

// `none` = domain exists but no records of this type; `transient` = the lookup
// itself failed (timeout/SERVFAIL) and the verdict is unknown → fail open.
type ResolveOutcome = 'has' | 'none' | 'transient'

function classifyDnsError(error: unknown): 'none' | 'transient' {
    const code = (error as NodeJS.ErrnoException | undefined)?.code
    // ENOTFOUND (NXDOMAIN) and ENODATA are definitive "nothing here" answers.
    // Everything else (ETIMEOUT, ESERVFAIL, EREFUSED, ECONNREFUSED, …) is a
    // resolver problem, not a verdict about the domain — fail open.
    if (code === 'ENOTFOUND' || code === 'ENODATA' || code === 'NOTFOUND' || code === 'NODATA') {
        return 'none'
    }
    return 'transient'
}

/**
 * Predicts hard bounces before a send reaches SES: an address with broken
 * syntax or a domain with no mail servers can never deliver, so attempting the
 * send only burns our bounce rate. Verdicts are cached per domain (in-process +
 * the dedicated SES Valkey) so a large batch to the same domains pays the DNS
 * cost once, protecting the *current* batch rather than only the next one.
 *
 * Fail-open by design: only a definitive "this domain has no mail exchange"
 * blocks a send. A DNS hiccup must never nuke a batch of legitimate mail.
 */
export class EmailValidationService {
    private readonly resolver: Resolver
    private readonly localCache = new Map<string, CacheEntry>()
    private readonly inFlight = new Map<string, Promise<boolean>>()

    constructor(private valkey: RedisV2 | null) {
        this.resolver = new Resolver({ timeout: DNS_TIMEOUT_MS, tries: DNS_TRIES })
    }

    /**
     * Returns a human-readable reason to skip the send, or null to proceed.
     * Only acts on `function_email` actions; anything else (missing recipient,
     * non-email action) returns null so the existing send path is untouched.
     */
    public async getSkipReason(
        invocation: CyclotronJobInvocationHogFunction,
        action: HogFlowAction
    ): Promise<string | null> {
        if (action.type !== 'function_email') {
            return null
        }

        const rawEmail = invocation.state.globals.inputs?.email?.to?.email
        if (typeof rawEmail !== 'string' || rawEmail.trim().length === 0) {
            // Missing recipient is handled (and surfaced) by the existing opt-out check.
            return null
        }
        const email = rawEmail.trim()

        if (!EMAIL_SYNTAX_RE.test(email)) {
            cdpEmailMxValidationTotal.inc({ result: 'invalid_syntax' })
            return this.skip(
                invocation.teamId,
                'invalid_syntax',
                `Skipping send: "${email}" is not a valid email address, so it would hard bounce.`
            )
        }

        // domainToASCII lowercases and punycodes IDN domains (`bücher.example` →
        // `xn--bcher-kva.example`) so the resolver sees the form DNS actually stores;
        // without it every internationalized domain would error and bypass validation.
        // It passes unconvertible garbage through unchanged — the lookup then fails
        // open, which is the safe direction.
        const rawDomain = email.slice(email.lastIndexOf('@') + 1)
        const domain = domainToASCII(rawDomain) || rawDomain.toLowerCase()
        const deliverable = await this.resolveDeliverability(domain)
        if (!deliverable) {
            return this.skip(
                invocation.teamId,
                'invalid_domain',
                `Skipping send: the domain "${domain}" has no reachable mail servers, so this message would hard bounce.`
            )
        }
        return null
    }

    private skip(teamId: number, reason: 'invalid_syntax' | 'invalid_domain', message: string): string {
        cdpEmailMxSkippedTotal.inc({ team_id: String(teamId), reason })
        return message
    }

    private async resolveDeliverability(domain: string): Promise<boolean> {
        const local = this.localCache.get(domain)
        if (local && local.expiresAt > Date.now()) {
            cdpEmailMxValidationTotal.inc({ result: local.transient ? 'transient_backoff' : 'hit_local' })
            return local.deliverable
        }

        // Coalesce concurrent lookups for the same domain — a big batch fires
        // thousands of parallel invocations; the first does the work, the rest wait.
        const existing = this.inFlight.get(domain)
        if (existing) {
            return existing
        }
        const promise = this.resolveUncached(domain).finally(() => this.inFlight.delete(domain))
        this.inFlight.set(domain, promise)
        return promise
    }

    private async resolveUncached(domain: string): Promise<boolean> {
        const cached = await this.readValkey(domain)
        if (cached !== null) {
            cdpEmailMxValidationTotal.inc({ result: 'hit_valkey' })
            this.setLocal(domain, {
                deliverable: cached,
                expiresAt: Date.now() + (cached ? POSITIVE_TTL_MS : NEGATIVE_TTL_MS),
            })
            return cached
        }

        const status = await this.dnsLookup(domain)
        if (status === 'transient') {
            cdpEmailMxValidationTotal.inc({ result: 'transient_error' })
            // Unknown verdict — fail open, remember only briefly and only locally,
            // so a resolver outage neither blocks sends nor stalls every send to
            // this domain on a fresh 3s-timeout lookup.
            this.setLocal(domain, { deliverable: true, transient: true, expiresAt: Date.now() + TRANSIENT_BACKOFF_MS })
            return true
        }

        const deliverable = status === 'valid'
        cdpEmailMxValidationTotal.inc({ result: deliverable ? 'valid' : 'invalid_domain' })
        this.setLocal(domain, {
            deliverable,
            expiresAt: Date.now() + (deliverable ? POSITIVE_TTL_MS : NEGATIVE_TTL_MS),
        })
        await this.writeValkey(domain, deliverable)
        return deliverable
    }

    private async dnsLookup(domain: string): Promise<'valid' | 'invalid' | 'transient'> {
        let mxRecords: MxRecord[]
        try {
            mxRecords = await this.resolver.resolveMx(domain)
        } catch (error) {
            const outcome = classifyDnsError(error)
            if (outcome === 'transient') {
                return 'transient'
            }
            // No MX record set → fall through to the A/AAAA implicit-MX check below.
            mxRecords = []
        }

        if (mxRecords.length > 0) {
            // RFC 7505 "null MX": a single `.`/empty exchange means the domain
            // explicitly accepts no mail — a definitive block, no A/AAAA fallback.
            const hasRealExchange = mxRecords.some((r) => r.exchange && r.exchange !== '.')
            return hasRealExchange ? 'valid' : 'invalid'
        }

        // RFC 5321 implicit MX: no MX records means the A/AAAA record is the mail target.
        const a = await this.tryResolve(() => this.resolver.resolve4(domain))
        if (a === 'transient') {
            return 'transient'
        }
        if (a === 'has') {
            return 'valid'
        }
        const aaaa = await this.tryResolve(() => this.resolver.resolve6(domain))
        if (aaaa === 'transient') {
            return 'transient'
        }
        return aaaa === 'has' ? 'valid' : 'invalid'
    }

    private async tryResolve(fn: () => Promise<unknown[]>): Promise<ResolveOutcome> {
        try {
            const records = await fn()
            return records.length > 0 ? 'has' : 'none'
        } catch (error) {
            return classifyDnsError(error)
        }
    }

    private setLocal(domain: string, entry: CacheEntry): void {
        // FIFO eviction via Map insertion order — cheap, and precision doesn't
        // matter here: an evicted hot domain just costs one Valkey/DNS round trip.
        if (!this.localCache.has(domain) && this.localCache.size >= MAX_LOCAL_CACHE_DOMAINS) {
            const oldest = this.localCache.keys().next().value
            if (oldest !== undefined) {
                this.localCache.delete(oldest)
            }
        }
        this.localCache.set(domain, entry)
    }

    private async readValkey(domain: string): Promise<boolean | null> {
        if (!this.valkey) {
            return null
        }
        // failOpen: a Valkey outage returns null (treated as a cache miss), never throws.
        const value = await this.valkey.useClient({ name: 'email-mx-read', failOpen: true }, (client) =>
            client.get(VALKEY_KEY_PREFIX + domain)
        )
        if (value === '1') {
            return true
        }
        if (value === '0') {
            return false
        }
        return null
    }

    private async writeValkey(domain: string, deliverable: boolean): Promise<void> {
        if (!this.valkey) {
            return
        }
        const ttlSeconds = Math.floor((deliverable ? POSITIVE_TTL_MS : NEGATIVE_TTL_MS) / 1000)
        await this.valkey.useClient({ name: 'email-mx-write', failOpen: true }, (client) =>
            client.set(VALKEY_KEY_PREFIX + domain, deliverable ? '1' : '0', 'EX', ttlSeconds)
        )
    }
}
