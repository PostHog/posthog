import { createHmac, timingSafeEqual } from 'crypto'
import { Counter } from 'prom-client'

import { buildIntegerMatcher } from '~/common/config/matchers'
import { logger } from '~/common/utils/logger'
import type { ValueMatcher } from '~/types'

export const INTERNAL_LOGS_HEADER = 'posthog-internal'

// The HTTP request header that capture-logs forwards as the `posthog-internal` Kafka header.
export const INTERNAL_LOGS_HTTP_HEADER = 'x-posthog-internal'

export const INTERNAL_SOURCE_HEADER = 'internal-source'

const SIGNATURE_VERSION = 'v1'

// No dot, because a dot divides the parts of the header value.
const SOURCE_PATTERN = /^[a-z0-9_]{1,64}$/
// Epoch seconds. A strict shape keeps milliseconds, signs and padding out of the freshness check.
const SIGNED_AT_PATTERN = /^[1-9][0-9]{9}$/

// Measured against capture's `created_at`, not this consumer's clock, so consumer lag and DLQ replays
// do not expire a signature. Covers producer and capture clock skew and a short producer retry.
const SIGNATURE_WINDOW_SECONDS = 5 * 60

export type InternalSourcePolicy = {
    /** Counts toward the team's logs usage, quota and rate limits. */
    billed: boolean
    /** Runs the team's sampling, drop, transformation, metric and retention rules. */
    teamRules: boolean
}

export type InternalLogs = InternalSourcePolicy & { source: string }

// A signer names the source and this map decides how it is handled, so a leaked key cannot invent
// a free source. Moving a source to billing changes its entry here, not the producer or the header.
export const INTERNAL_SOURCE_POLICIES: Readonly<Record<string, InternalSourcePolicy>> = {
    hog_flow: { billed: false, teamRules: false },
    // Each log_entries source moves unbilled, one at a time. Add a source when its producer starts signing.
    // hog_function: { billed: false, teamRules: false },
}

type NotInternalReason =
    | 'not_configured'
    | 'team_not_allowed'
    | 'invalid_signature'
    | 'stale_signature'
    | 'unknown_source'

const logsInternalLogsCounter = new Counter({
    name: 'logs_ingestion_internal_logs_total',
    help: 'Batches that carried the posthog-internal header, by outcome. A not_internal batch is billed as normal.',
    labelNames: ['outcome', 'reason'],
})

function parseKeys(commaSeparatedKeys: string): string[] {
    return commaSeparatedKeys
        .split(',')
        .map((key) => key.trim())
        .filter((key) => key.length > 0)
}

// No payload hash, because capture-logs re-encodes the request and the producer never sees the Kafka bytes.
function computeSignature(key: string, source: string, teamId: number, signedAt: string): string {
    const mac = createHmac('sha256', key).update(`${SIGNATURE_VERSION}|${source}|${teamId}|${signedAt}`).digest('hex')
    return `${SIGNATURE_VERSION}.${source}.${signedAt}.${mac}`
}

/** Sign once per HTTP attempt, because a retried signature can fall outside the window and be billed. */
export function signInternalLogs(
    commaSeparatedKeys: string,
    source: string,
    teamId: number,
    signedAt: Date = new Date()
): string {
    const [newestKey] = parseKeys(commaSeparatedKeys)
    if (!newestKey) {
        throw new Error('Cannot sign posthog-internal batch: no signing key configured')
    }
    if (!SOURCE_PATTERN.test(source)) {
        throw new Error(`Cannot sign posthog-internal batch: invalid source ${JSON.stringify(source)}`)
    }
    return computeSignature(newestKey, source, teamId, String(Math.floor(signedAt.getTime() / 1000)))
}

// Only a verified batch may set the `internal_source` column, so an incoming copy of the header is removed.
export function withoutInternalLogsHeaders(headers: Record<string, string>): Record<string, string> {
    const { [INTERNAL_LOGS_HEADER]: _signature, [INTERNAL_SOURCE_HEADER]: _source, ...rest } = headers
    return rest
}

export class InternalLogsVerifier {
    private readonly keys: string[]
    private readonly isTeamAllowed: ValueMatcher<number>

    constructor(
        commaSeparatedKeys: string,
        enabledTeams: string,
        private readonly policies: Readonly<Record<string, InternalSourcePolicy>> = INTERNAL_SOURCE_POLICIES
    ) {
        this.keys = parseKeys(commaSeparatedKeys)
        this.isTeamAllowed = buildIntegerMatcher(enabledTeams, true)
    }

    /** `createdAt` is the `created_at` Kafka header, which capture-logs sets when it receives the request. */
    verify(signature: string | undefined, teamId: number, createdAt: string | undefined): InternalLogs | undefined {
        if (signature === undefined) {
            return undefined
        }
        const [, source = '', signedAt = ''] = signature.split('.')
        const reason = this.notInternalReason(signature, source, signedAt, teamId, createdAt)
        // Own keys only, because a source like `constructor` resolves to an inherited policy with no `billed`.
        const policy = reason || !Object.hasOwn(this.policies, source) ? undefined : this.policies[source]
        if (!policy) {
            logsInternalLogsCounter.inc({ outcome: 'not_internal', reason: reason ?? 'unknown_source' })
            // The team is not a counter label, because a caller that rotates tokens would make its values unbounded.
            logger.warn('Internal logs header did not verify, batch billed as normal', {
                teamId,
                reason: reason ?? 'unknown_source',
            })
            return undefined
        }
        logsInternalLogsCounter.inc({ outcome: 'internal', reason: '' })
        return { source, ...policy }
    }

    private notInternalReason(
        signature: string,
        source: string,
        signedAt: string,
        teamId: number,
        createdAt: string | undefined
    ): NotInternalReason | null {
        if (this.keys.length === 0) {
            return 'not_configured'
        }
        if (!this.isTeamAllowed(teamId)) {
            return 'team_not_allowed'
        }
        if (!SOURCE_PATTERN.test(source) || !SIGNED_AT_PATTERN.test(signedAt)) {
            return 'invalid_signature'
        }
        const received = Buffer.from(signature)
        // Every key is tried, so a rotation can add a key before producers switch to it.
        const matches = this.keys.some((key) => {
            const expected = Buffer.from(computeSignature(key, source, teamId, signedAt))
            return expected.length === received.length && timingSafeEqual(expected, received)
        })
        if (!matches) {
            return 'invalid_signature'
        }
        // A missing or unparseable `created_at` gives NaN, which fails this comparison and bills the batch.
        const skewSeconds = Math.abs(Date.parse(createdAt ?? '') / 1000 - Number(signedAt))
        return skewSeconds <= SIGNATURE_WINDOW_SECONDS ? null : 'stale_signature'
    }
}
