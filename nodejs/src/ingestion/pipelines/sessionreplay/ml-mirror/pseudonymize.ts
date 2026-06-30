import { createHmac } from 'crypto'

/**
 * Deterministic, non-reversible pseudonym for an identifier. Same input → same
 * output (so the ML dataset can group by team/session/person), but without the
 * secret (held only by the ingester, never in the ML account) it can't be mapped
 * back. The namespace domain-separates ids so a teamId and sessionId with the
 * same value don't collide.
 */
export function pseudonymize(secret: string | Buffer, namespace: string, value: string): string {
    // Length-prefix the namespace so the join is unambiguous even if a value contains the delimiter.
    return createHmac('sha256', secret).update(`${namespace.length}:${namespace}:${value}`).digest('hex').slice(0, 32)
}

export const PSEUDONYM_TEAM = 'team'
export const PSEUDONYM_SESSION = 'session'
export const PSEUDONYM_DISTINCT_ID = 'distinct_id'
