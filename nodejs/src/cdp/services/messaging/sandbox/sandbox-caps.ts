import { createHash } from 'crypto'

import { RateLimiterService } from '../../rate-limiter/rate-limiter.service'

const SECONDS_PER_DAY = 86_400
const BUCKET_TTL_SECONDS = 2 * SECONDS_PER_DAY

export type SandboxCaps = { team: number; recipient: number }

export type SandboxCapClaim = { ok: true } | { ok: false; reason: 'daily_cap_reached' | 'cap_storage_unavailable' }

export type SandboxCapClaimRequest = {
    organizationId: string
    teamId: number
    storedAddress: string
    claimId: string
    attemptId: string
}

export async function claimSandboxCaps(
    limiter: RateLimiterService,
    caps: SandboxCaps,
    request: SandboxCapClaimRequest
): Promise<SandboxCapClaim> {
    if (!isValidCap(caps.team) || !isValidCap(caps.recipient)) {
        return { ok: false, reason: 'cap_storage_unavailable' }
    }
    const { keyPrefix, recipientDigest, claimKey } = capKeys(request)
    const bucket = (key: string, cap: number) => ({
        key,
        requested: 1,
        capacity: cap,
        refillPerSecond: cap / SECONDS_PER_DAY,
        ttlSeconds: BUCKET_TTL_SECONDS,
    })
    const claim = await limiter.claimAllOrNothingAcross(
        [
            bucket(`${keyPrefix}/recipient/${recipientDigest}`, caps.recipient),
            bucket(`${keyPrefix}/project/${request.teamId}`, caps.team),
        ],
        { key: claimKey, attempt: request.attemptId, ttlSeconds: BUCKET_TTL_SECONDS }
    )
    if (claim === 'granted') {
        return { ok: true }
    }
    return { ok: false, reason: claim === 'denied' ? 'daily_cap_reached' : 'cap_storage_unavailable' }
}

export async function markSandboxCapsClaimSent(
    limiter: RateLimiterService,
    request: SandboxCapClaimRequest
): Promise<boolean> {
    return await limiter.markClaimSpent({ key: capKeys(request).claimKey, attempt: request.attemptId })
}

function capKeys({ organizationId, teamId, storedAddress, claimId }: SandboxCapClaimRequest): {
    keyPrefix: string
    recipientDigest: string
    claimKey: string
} {
    const keyPrefix = `@posthog/sandbox-email/{${organizationId}}`
    const recipientDigest = createHash('sha256').update(storedAddress.toLowerCase()).digest('hex')
    const claimDigest = createHash('sha256').update(`${teamId}\n${recipientDigest}\n${claimId}`).digest('hex')
    return { keyPrefix, recipientDigest, claimKey: `${keyPrefix}/claim/${claimDigest}` }
}

function isValidCap(cap: number): boolean {
    return Number.isSafeInteger(cap) && cap > 0
}
