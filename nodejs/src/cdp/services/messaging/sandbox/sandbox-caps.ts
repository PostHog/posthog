import { createHash, randomUUID } from 'crypto'
import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'

import { ClaimRequest, RateLimiterService } from '../../rate-limiter/rate-limiter.service'

const SECONDS_PER_DAY = 86_400
const BUCKET_TTL_SECONDS = 2 * SECONDS_PER_DAY

export type SandboxCaps = { team: number; warning: number }

export type SandboxCapClaim =
    | {
          ok: true
          markSending: () => Promise<boolean>
          releaseUnsent: () => Promise<boolean>
          refundUnsent: () => Promise<boolean>
          countAccepted: () => Promise<void>
      }
    | { ok: false; reason: 'daily_cap_reached' | 'cap_storage_unavailable' }

export type SandboxCapClaimRequest = {
    organizationId: string
    teamId: number
    storedAddress: string
    claimId: string
    isTest?: boolean
}

// Workers of the previous release cap each recipient. This release charges and refunds that bucket as well, so a
// claim that moves between releases during the deploy refunds what it charged. The capacity never denies a send.
const PREVIOUS_RELEASE_RECIPIENT_CAPACITY = 1_000_000_000

const sandboxTeamWarningTotal = new Counter({
    name: 'cdp_sandbox_email_team_warning_total',
    help: 'Sandbox emails that SES accepted from a project past its daily warning threshold',
})

export async function claimSandboxCaps(
    limiter: RateLimiterService,
    caps: SandboxCaps,
    request: SandboxCapClaimRequest,
    now: Date = new Date()
): Promise<SandboxCapClaim> {
    if (!isValidCap(caps.team) || !isValidCap(caps.warning)) {
        return { ok: false, reason: 'cap_storage_unavailable' }
    }
    const { organizationId, teamId, storedAddress, claimId } = request
    const keyPrefix = `@posthog/sandbox-email/{${organizationId}}`
    const countAccepted = () => countAcceptedSend(limiter, caps.warning, request, keyPrefix, now)
    if (request.isTest) {
        return {
            ok: true,
            markSending: () => Promise.resolve(true),
            releaseUnsent: () => Promise.resolve(true),
            refundUnsent: () => Promise.resolve(true),
            countAccepted,
        }
    }
    // The recipient stays in the claim identity, so a retry finds the claim that another worker version made.
    const recipientDigest = createHash('sha256').update(storedAddress.toLowerCase()).digest('hex')
    const claimDigest = createHash('sha256').update(`${teamId}\n${recipientDigest}\n${claimId}`).digest('hex')
    const claimKey = `${keyPrefix}/claim/${claimDigest}`
    const attempt = randomUUID()
    const buckets = [
        {
            ...dailyBucket(`${keyPrefix}/recipient/${recipientDigest}`, caps.team),
            capacity: PREVIOUS_RELEASE_RECIPIENT_CAPACITY,
        },
        dailyBucket(`${keyPrefix}/project/${teamId}`, caps.team),
    ]
    const claim = await limiter.claimAllOrNothingAcross(buckets, {
        key: claimKey,
        attempt,
        ttlSeconds: BUCKET_TTL_SECONDS,
    })
    if (claim !== 'granted') {
        return { ok: false, reason: claim === 'denied' ? 'daily_cap_reached' : 'cap_storage_unavailable' }
    }
    return {
        ok: true,
        markSending: () => limiter.markClaimSpent({ key: claimKey, attempt }),
        releaseUnsent: () => limiter.releaseClaimSpend({ key: claimKey, attempt }),
        refundUnsent: () => limiter.refundClaimSpend({ key: claimKey, attempt }, buckets),
        countAccepted,
    }
}

async function countAcceptedSend(
    limiter: RateLimiterService,
    threshold: number,
    { organizationId, teamId }: SandboxCapClaimRequest,
    keyPrefix: string,
    now: Date
): Promise<void> {
    const utcDay = now.toISOString().slice(0, 10)
    const accepted = await limiter.incrementCounter(
        `${keyPrefix}/project-accepted/${teamId}/${utcDay}`,
        BUCKET_TTL_SECONDS
    )
    if (accepted !== null && accepted > threshold) {
        sandboxTeamWarningTotal.inc()
        logger.warn('Sandbox email project is past its daily warning threshold', {
            team_id: teamId,
            organization_id: organizationId,
            threshold,
        })
    }
}

function dailyBucket(key: string, cap: number): ClaimRequest {
    return {
        key,
        requested: 1,
        capacity: cap,
        refillPerSecond: cap / SECONDS_PER_DAY,
        ttlSeconds: BUCKET_TTL_SECONDS,
    }
}

function isValidCap(cap: number): boolean {
    return Number.isSafeInteger(cap) && cap > 0
}
