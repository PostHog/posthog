import { createHash } from 'crypto'

import { RateLimiterService } from '../../rate-limiter/rate-limiter.service'

const SECONDS_PER_DAY = 86_400
const BUCKET_TTL_SECONDS = 2 * SECONDS_PER_DAY

export type SandboxCaps = { team: number; recipient: number }

export type SandboxCapClaim = { ok: true } | { ok: false; reason: 'daily_cap_reached' | 'cap_storage_unavailable' }

export async function claimSandboxCaps(
    limiter: RateLimiterService,
    caps: SandboxCaps,
    {
        organizationId,
        teamId,
        storedAddress,
        claimId,
    }: { organizationId: string; teamId: number; storedAddress: string; claimId: string }
): Promise<SandboxCapClaim> {
    if (!isValidCap(caps.team) || !isValidCap(caps.recipient)) {
        return { ok: false, reason: 'cap_storage_unavailable' }
    }
    const recipientDigest = createHash('sha256').update(storedAddress.toLowerCase()).digest('hex')
    const keyPrefix = `@posthog/sandbox-email/{${organizationId}}`
    const bucket = (key: string, cap: number) => ({
        key,
        requested: 1,
        capacity: cap,
        refillPerSecond: cap / SECONDS_PER_DAY,
        ttlSeconds: BUCKET_TTL_SECONDS,
    })
    const claimDigest = createHash('sha256').update(claimId).digest('hex')
    const claim = await limiter.claimAllOrNothingAcross(
        [
            bucket(`${keyPrefix}/recipient/${recipientDigest}`, caps.recipient),
            bucket(`${keyPrefix}/project/${teamId}`, caps.team),
        ],
        { key: `${keyPrefix}/claim/${claimDigest}`, ttlSeconds: BUCKET_TTL_SECONDS }
    )
    if (claim === 'granted') {
        return { ok: true }
    }
    return { ok: false, reason: claim === 'denied' ? 'daily_cap_reached' : 'cap_storage_unavailable' }
}

function isValidCap(cap: number): boolean {
    return Number.isSafeInteger(cap) && cap > 0
}
