/**
 * Content reference for an inlined replay image: the ml-mirror producer swaps the raw image for one of
 * these, this consumer writes the scrubbed image to S3 under the same reference, and training resolves
 * block -> image by it. Format `image:{pseudo_team}:{hash}`, where `pseudo_team` is the non-reversible HMAC
 * team pseudonym (ml-mirror/pseudonymize.ts) and `hash` = 132-bit sha256, base64url, 22 chars. Using the
 * pseudonym rather than the raw team id keeps raw team ids out of the ML bucket, matching the block-metadata
 * dataset (which pseudonymises team_id the same way); it still scopes per-team dedup because a given team
 * always maps to the same pseudonym.
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
