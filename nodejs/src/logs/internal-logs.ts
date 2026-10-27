import { createHash, createHmac, timingSafeEqual } from 'crypto'
import { Counter } from 'prom-client'

import { buildIntegerMatcher } from '~/common/config/matchers'
import type { ValueMatcher } from '~/types'

export const INTERNAL_LOGS_HEADER = 'posthog-internal'

export const INTERNAL_SOURCE_HEADER = 'internal-source'

const SIGNATURE_VERSION = 'v1'

// No dot, because a dot divides the parts of the header value.
const SOURCE_PATTERN = /^[a-z0-9_]{1,64}$/

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

type RejectReason = 'not_configured' | 'team_not_allowed' | 'invalid_signature' | 'unknown_source'

const logsInternalLogsCounter = new Counter({
    name: 'logs_ingestion_internal_logs_total',
    help: 'Batches that carried the posthog-internal header, by outcome. A rejected batch is billed as normal.',
    labelNames: ['outcome', 'reason'],
})

function parseKeys(commaSeparatedKeys: string): string[] {
    return commaSeparatedKeys
        .split(',')
        .map((key) => key.trim())
        .filter((key) => key.length > 0)
}

function sha256Hex(payload: Buffer): string {
    return createHash('sha256').update(payload).digest('hex')
}

// No expiry, because a batch that waits in Kafka through consumer lag or a DLQ replay must stay internal.
function computeSignature(key: string, source: string, teamId: number, payloadSha256: string): string {
    const mac = createHmac('sha256', key)
        .update(`${SIGNATURE_VERSION}|${source}|${teamId}|${payloadSha256}`)
        .digest('hex')
    return `${SIGNATURE_VERSION}.${source}.${mac}`
}

export function signInternalLogs(commaSeparatedKeys: string, source: string, teamId: number, payload: Buffer): string {
    const [newestKey] = parseKeys(commaSeparatedKeys)
    if (!newestKey) {
        throw new Error('Cannot sign posthog-internal batch: no signing key configured')
    }
    if (!SOURCE_PATTERN.test(source)) {
        throw new Error(`Cannot sign posthog-internal batch: invalid source ${JSON.stringify(source)}`)
    }
    return computeSignature(newestKey, source, teamId, sha256Hex(payload))
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

    verify(signature: string | undefined, teamId: number, payload: Buffer | null): InternalLogs | undefined {
        if (signature === undefined) {
            return undefined
        }
        const source = signature.split('.')[1] ?? ''
        const reason = this.rejectReason(signature, source, teamId, payload)
        // Own keys only, because a source like `constructor` resolves to an inherited policy with no `billed`.
        const policy = reason || !Object.hasOwn(this.policies, source) ? undefined : this.policies[source]
        if (!policy) {
            logsInternalLogsCounter.inc({ outcome: 'rejected', reason: reason ?? 'unknown_source' })
            return undefined
        }
        logsInternalLogsCounter.inc({ outcome: 'accepted', reason: '' })
        return { source, ...policy }
    }

    private rejectReason(
        signature: string,
        source: string,
        teamId: number,
        payload: Buffer | null
    ): RejectReason | null {
        if (this.keys.length === 0) {
            return 'not_configured'
        }
        if (!this.isTeamAllowed(teamId)) {
            return 'team_not_allowed'
        }
        if (payload === null || !SOURCE_PATTERN.test(source)) {
            return 'invalid_signature'
        }
        const received = Buffer.from(signature)
        const payloadSha256 = sha256Hex(payload)
        // Every key is tried, so a rotation can add a key before producers switch to it.
        const matches = this.keys.some((key) => {
            const expected = Buffer.from(computeSignature(key, source, teamId, payloadSha256))
            return expected.length === received.length && timingSafeEqual(expected, received)
        })
        return matches ? null : 'invalid_signature'
    }
}
