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
      }
    | { ok: false; reason: 'daily_cap_reached' | 'cap_storage_unavailable' }

export type SandboxCapClaimRequest = {
    organizationId: string
    teamId: number
    claimId: string
}

const sandboxTeamWarningTotal = new Counter({
    name: 'cdp_sandbox_email_team_warning_total',
    help: 'Sandbox email sends from a project past its daily warning threshold',
})

export async function claimSandboxCaps(
    limiter: RateLimiterService,
    caps: SandboxCaps,
    request: SandboxCapClaimRequest
): Promise<SandboxCapClaim> {
    if (!isValidCap(caps.team) || !isValidCap(caps.warning)) {
        return { ok: false, reason: 'cap_storage_unavailable' }
    }
    const { organizationId, teamId, claimId } = request
    const keyPrefix = `@posthog/sandbox-email/{${organizationId}}`
    const claimDigest = createHash('sha256').update(`${teamId}\n${claimId}`).digest('hex')
    const claimKey = `${keyPrefix}/claim/${claimDigest}`
    const attempt = randomUUID()
    const buckets = [dailyBucket(`${keyPrefix}/project/${teamId}`, caps.team)]
    const claim = await limiter.claimAllOrNothingAcross(buckets, {
        key: claimKey,
        attempt,
        ttlSeconds: BUCKET_TTL_SECONDS,
    })
    if (claim !== 'granted') {
        return { ok: false, reason: claim === 'denied' ? 'daily_cap_reached' : 'cap_storage_unavailable' }
    }
    await warnPastThreshold(limiter, caps.warning, request, keyPrefix, claimDigest)
    return {
        ok: true,
        markSending: () => limiter.markClaimSpent({ key: claimKey, attempt }),
        releaseUnsent: () => limiter.releaseClaimSpend({ key: claimKey, attempt }),
        refundUnsent: () => limiter.refundClaimSpend({ key: claimKey, attempt }, buckets),
    }
}

// The warning bucket never blocks a send. Its own claim key makes a retried send count once.
async function warnPastThreshold(
    limiter: RateLimiterService,
    threshold: number,
    { organizationId, teamId }: SandboxCapClaimRequest,
    keyPrefix: string,
    claimDigest: string
): Promise<void> {
    const warning = await limiter.claimAllOrNothingAcross(
        [dailyBucket(`${keyPrefix}/project-warning/${teamId}`, threshold)],
        { key: `${keyPrefix}/warning-claim/${claimDigest}`, attempt: randomUUID(), ttlSeconds: BUCKET_TTL_SECONDS }
    )
    if (warning === 'denied') {
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
