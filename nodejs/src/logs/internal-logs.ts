import { createHash, createHmac, timingSafeEqual } from 'crypto'
import { Counter } from 'prom-client'

import { buildIntegerMatcher } from '~/common/config/matchers'
import type { ValueMatcher } from '~/types'

/**
 * Kafka header that marks a batch as logs PostHog produced about the team's use of PostHog. PostHog owns
 * their storage and processing, so the consumer does not bill them or apply the team's log rules.
 */
export const INTERNAL_LOGS_HEADER = 'posthog-internal'

const SIGNATURE_VERSION = 'v1'

type RejectReason = 'not_configured' | 'team_not_allowed' | 'invalid_signature'

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

/**
 * The signature covers the team id and a hash of the payload. The team id stops a signature from
 * moving to another team's batch, and the hash stops it from moving to different data. It has no
 * expiry on purpose: a batch that waits in Kafka through consumer lag or a DLQ replay must stay internal.
 */
function computeSignature(key: string, teamId: number, payloadSha256: string): string {
    const mac = createHmac('sha256', key).update(`${SIGNATURE_VERSION}|${teamId}|${payloadSha256}`).digest('hex')
    return `${SIGNATURE_VERSION}.${mac}`
}

/** Signs a batch with the newest key. Keys are comma-separated, newest first. */
export function signInternalLogs(commaSeparatedKeys: string, teamId: number, payload: Buffer): string {
    const [newestKey] = parseKeys(commaSeparatedKeys)
    if (!newestKey) {
        throw new Error('Cannot sign posthog-internal batch: no signing key configured')
    }
    return computeSignature(newestKey, teamId, sha256Hex(payload))
}

/** Downstream topics have no use for the signature, so it stops at this consumer. */
export function withoutInternalLogsHeader(headers: Record<string, string>): Record<string, string> {
    const { [INTERNAL_LOGS_HEADER]: _signature, ...rest } = headers
    return rest
}

/**
 * Decides whether a batch is internal. Only a holder of the signing key can make a signature that
 * passes. Any failure returns false, so the batch is billed and never dropped.
 */
export class InternalLogsVerifier {
    private readonly keys: string[]
    private readonly isTeamAllowed: ValueMatcher<number>

    /**
     * `enabledTeams` is a comma-separated team-ID list, or empty for none. It has no `*` form, because the
     * list is what bounds a leaked key to named teams.
     */
    constructor(commaSeparatedKeys: string, enabledTeams: string) {
        this.keys = parseKeys(commaSeparatedKeys)
        this.isTeamAllowed = buildIntegerMatcher(enabledTeams, false)
    }

    isInternal(signature: string | undefined, teamId: number, payload: Buffer | null): boolean {
        if (signature === undefined) {
            return false
        }
        const reason = this.rejectReason(signature, teamId, payload)
        if (reason) {
            logsInternalLogsCounter.inc({ outcome: 'rejected', reason })
            return false
        }
        logsInternalLogsCounter.inc({ outcome: 'accepted', reason: '' })
        return true
    }

    private rejectReason(signature: string, teamId: number, payload: Buffer | null): RejectReason | null {
        if (this.keys.length === 0) {
            return 'not_configured'
        }
        // The allowlist bounds what a leaked key can mark internal.
        if (!this.isTeamAllowed(teamId)) {
            return 'team_not_allowed'
        }
        if (payload === null) {
            return 'invalid_signature'
        }
        const received = Buffer.from(signature)
        const payloadSha256 = sha256Hex(payload)
        // Every key is tried so that a rotation can add a new key before producers switch to it.
        const matches = this.keys.some((key) => {
            const expected = Buffer.from(computeSignature(key, teamId, payloadSha256))
            return expected.length === received.length && timingSafeEqual(expected, received)
        })
        return matches ? null : 'invalid_signature'
    }
}
