import { createHash, randomUUID } from 'crypto'

import { RateLimiterService } from '../../rate-limiter/rate-limiter.service'

const SECONDS_PER_DAY = 86_400
const BUCKET_TTL_SECONDS = 2 * SECONDS_PER_DAY

export type SandboxCaps = { team: number; recipient: number }

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
    storedAddress: string
    claimId: string
}

export async function claimSandboxCaps(
    limiter: RateLimiterService,
    caps: SandboxCaps,
    request: SandboxCapClaimRequest
): Promise<SandboxCapClaim> {
    if (!isValidCap(caps.team) || !isValidCap(caps.recipient)) {
        return { ok: false, reason: 'cap_storage_unavailable' }
    }
    const { organizationId, teamId, storedAddress, claimId } = request
    const keyPrefix = `@posthog/sandbox-email/{${organizationId}}`
    const recipientDigest = createHash('sha256').update(storedAddress.toLowerCase()).digest('hex')
    const claimDigest = createHash('sha256').update(`${teamId}\n${recipientDigest}\n${claimId}`).digest('hex')
    const claimKey = `${keyPrefix}/claim/${claimDigest}`
    const attempt = randomUUID()
    const bucket = (key: string, cap: number) => ({
        key,
        requested: 1,
        capacity: cap,
        refillPerSecond: cap / SECONDS_PER_DAY,
        ttlSeconds: BUCKET_TTL_SECONDS,
    })
    const buckets = [
        bucket(`${keyPrefix}/recipient/${recipientDigest}`, caps.recipient),
        bucket(`${keyPrefix}/project/${teamId}`, caps.team),
    ]
    const claim = await limiter.claimAllOrNothingAcross(buckets, {
        key: claimKey,
        attempt,
        ttlSeconds: BUCKET_TTL_SECONDS,
    })
    if (claim === 'granted') {
        return {
            ok: true,
            markSending: () => limiter.markClaimSpent({ key: claimKey, attempt }),
            releaseUnsent: () => limiter.releaseClaimSpend({ key: claimKey, attempt }),
            refundUnsent: () => limiter.refundClaimSpend({ key: claimKey, attempt }, buckets),
        }
    }
    return { ok: false, reason: claim === 'denied' ? 'daily_cap_reached' : 'cap_storage_unavailable' }
}

function isValidCap(cap: number): boolean {
    return Number.isSafeInteger(cap) && cap > 0
}
