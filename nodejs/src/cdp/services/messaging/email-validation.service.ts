import { MxRecord } from 'node:dns'
import { Resolver } from 'node:dns/promises'
import { Counter } from 'prom-client'

import { HogFlowAction } from '~/cdp/schema/hogflow'
import { buildIntegerMatcher } from '~/common/config/config'
import { RedisV2 } from '~/common/redis/redis-v2'
import { ValueMatcher } from '~/types'

import { CdpConfig } from '../../config'
import { CyclotronJobInvocationHogFunction } from '../../types'

const cdpEmailMxValidationTotal = new Counter({
    name: 'cdp_email_mx_validation_total',
    help: 'Pre-send email validation outcomes. `invalid_syntax`/`invalid_domain` are predicted hard bounces we skipped before hitting SES; `transient_error` means DNS was unreliable so we allowed the send (fail-open); `hit_*` are cache hits.',
    labelNames: ['result'],
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

// Bound per-lookup latency: the email worker must not stall on a slow resolver.
const DNS_TIMEOUT_MS = 3000
const DNS_TRIES = 1

const REDIS_KEY_PREFIX = '@posthog/cdp/email-mx/'

type CacheEntry = { deliverable: boolean; expiresAt: number }

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
 * Redis) so a large batch to the same domains pays the DNS cost once, protecting
 * the *current* batch rather than only the next one.
 *
 * Fail-open by design: only a definitive "this domain has no mail exchange"
 * blocks a send. A DNS hiccup must never nuke a batch of legitimate mail.
 */
export class EmailValidationService {
    private readonly teamMatcher: ValueMatcher<number>
    private readonly resolver: Resolver
    private readonly localCache = new Map<string, CacheEntry>()
    private readonly inFlight = new Map<string, Promise<boolean>>()

    constructor(
        config: Pick<CdpConfig, 'CDP_EMAIL_MX_VALIDATION_TEAMS'>,
        private redis: RedisV2 | null
    ) {
        this.teamMatcher = buildIntegerMatcher(config.CDP_EMAIL_MX_VALIDATION_TEAMS, true)
        this.resolver = new Resolver({ timeout: DNS_TIMEOUT_MS, tries: DNS_TRIES })
    }

    /**
     * Returns a human-readable reason to skip the send, or null to proceed.
     * Only acts on `function_email` actions for gated teams; anything else
     * (missing recipient, ungated team, non-email action) returns null so the
     * existing send path is untouched.
     */
    public async getSkipReason(
        invocation: CyclotronJobInvocationHogFunction,
        action: HogFlowAction
    ): Promise<string | null> {
        if (action.type !== 'function_email' || !this.teamMatcher(invocation.teamId)) {
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
            return `Skipping send: "${email}" is not a valid email address, so it would hard bounce.`
        }

        const domain = email.slice(email.lastIndexOf('@') + 1).toLowerCase()
        const deliverable = await this.resolveDeliverability(domain)
        if (!deliverable) {
            return `Skipping send: the domain "${domain}" has no reachable mail servers, so this message would hard bounce.`
        }
        return null
    }

    private async resolveDeliverability(domain: string): Promise<boolean> {
        const local = this.localCache.get(domain)
        if (local && local.expiresAt > Date.now()) {
            cdpEmailMxValidationTotal.inc({ result: 'hit_local' })
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
        const cached = await this.readRedis(domain)
        if (cached !== null) {
            cdpEmailMxValidationTotal.inc({ result: 'hit_redis' })
            this.setLocal(domain, cached)
            return cached
        }

        const status = await this.dnsLookup(domain)
        if (status === 'transient') {
            cdpEmailMxValidationTotal.inc({ result: 'transient_error' })
            // Unknown verdict — fail open and don't cache, so a resolver blip
            // doesn't get frozen into a day of blocked sends.
            return true
        }

        const deliverable = status === 'valid'
        cdpEmailMxValidationTotal.inc({ result: deliverable ? 'valid' : 'invalid_domain' })
        this.setLocal(domain, deliverable)
        await this.writeRedis(domain, deliverable)
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

    private setLocal(domain: string, deliverable: boolean): void {
        this.localCache.set(domain, {
            deliverable,
            expiresAt: Date.now() + (deliverable ? POSITIVE_TTL_MS : NEGATIVE_TTL_MS),
        })
    }

    private async readRedis(domain: string): Promise<boolean | null> {
        if (!this.redis) {
            return null
        }
        // failOpen: a Redis outage returns null (treated as a cache miss), never throws.
        const value = await this.redis.useClient({ name: 'email-mx-read', failOpen: true }, (client) =>
            client.get(REDIS_KEY_PREFIX + domain)
        )
        if (value === '1') {
            return true
        }
        if (value === '0') {
            return false
        }
        return null
    }

    private async writeRedis(domain: string, deliverable: boolean): Promise<void> {
        if (!this.redis) {
            return
        }
        const ttlSeconds = Math.floor((deliverable ? POSITIVE_TTL_MS : NEGATIVE_TTL_MS) / 1000)
        await this.redis.useClient({ name: 'email-mx-write', failOpen: true }, (client) =>
            client.set(REDIS_KEY_PREFIX + domain, deliverable ? '1' : '0', 'EX', ttlSeconds)
        )
    }
}
