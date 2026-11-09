import { createHash } from 'crypto'

import { RateLimiterService } from '../../rate-limiter/rate-limiter.service'

const SECONDS_PER_DAY = 86_400
const BUCKET_TTL_SECONDS = 2 * SECONDS_PER_DAY
const RESERVE_ON_DENY_MS = 1_000

export type SandboxCaps = { team: number; recipient: number }

export type SandboxCapClaim = { ok: true } | { ok: false; reason: 'daily_cap_reached' | 'cap_storage_unavailable' }

export async function claimSandboxCaps(
    limiter: RateLimiterService,
    caps: SandboxCaps,
    { organizationId, teamId, storedAddress }: { organizationId: string; teamId: number; storedAddress: string }
): Promise<SandboxCapClaim> {
    if (!isValidCap(caps.team) || !isValidCap(caps.recipient)) {
        return { ok: false, reason: 'cap_storage_unavailable' }
    }
    const recipientDigest = createHash('sha256').update(storedAddress.toLowerCase()).digest('hex')
    for (const [key, cap] of [
        [`@posthog/sandbox-email/recipient/${organizationId}/${recipientDigest}`, caps.recipient],
        [`@posthog/sandbox-email/project/${teamId}`, caps.team],
    ] as const) {
        const claim = await limiter.claimAllOrNothing(
            {
                key,
                requested: 1,
                capacity: cap,
                refillPerSecond: cap / SECONDS_PER_DAY,
                ttlSeconds: BUCKET_TTL_SECONDS,
            },
            RESERVE_ON_DENY_MS
        )
        if (!claim.granted) {
            return { ok: false, reason: claim.retryAfterMs === null ? 'cap_storage_unavailable' : 'daily_cap_reached' }
        }
    }
    return { ok: true }
}

function isValidCap(cap: number): boolean {
    return Number.isSafeInteger(cap) && cap > 0
}
