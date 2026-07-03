/**
 * Content reference for an inlined replay image, format `image:{pseudo_team}:{hash}`: the producer swaps a
 * raw image for one, the consumer stores the scrubbed bytes under it, training joins block -> image by it.
 * `pseudo_team` is the non-reversible HMAC team pseudonym (ml-mirror/pseudonymize.ts), `hash` a 22-char
 * base64url sha256 slice; the pseudonym keeps raw team ids out of the ML bucket while still scoping per-team dedup.
 */
import { createHash } from 'node:crypto'

const PREFIX = 'image'
// pseudo_team is pseudonymize()'s 32-char hex HMAC digest; hash is a 22-char base64url sha256 slice.
const REF_RE = /^image:([0-9a-f]{32}):([A-Za-z0-9_-]{22})$/

/** Content-only hash (not team-scoped); the reference's pseudo_team segment provides per-tenant separation. */
export function hashImageBytes(bytes: Buffer): string {
    return createHash('sha256').update(bytes).digest('base64url').slice(0, 22)
}

export function imageRef(pseudoTeam: string, hash: string): string {
    return `${PREFIX}:${pseudoTeam}:${hash}`
}

export function isImageRef(s: string): boolean {
    return REF_RE.test(s)
}

export function parseImageRef(s: string): { pseudoTeam: string; hash: string } | null {
    const m = REF_RE.exec(s)
    return m ? { pseudoTeam: m[1], hash: m[2] } : null
}
