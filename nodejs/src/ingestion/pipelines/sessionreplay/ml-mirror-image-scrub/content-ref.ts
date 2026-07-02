/**
 * Content reference for an inlined replay image: the ml-mirror producer swaps the raw image for one of
 * these, this consumer writes the scrubbed image to S3 under the same reference, and training resolves
 * block -> image by it. Format `image:{team_id}:{hash}`, hash = 132-bit sha256, base64url, 22 chars. The
 * team_id prefix scopes dedup and S3 storage per team, so identical bytes in two teams never share an object.
 */
import { createHash } from 'node:crypto'

const PREFIX = 'image'
const REF_RE = /^image:(\d+):([A-Za-z0-9_-]{22})$/

/** Content-only hash (not team-scoped); the reference's team prefix provides per-tenant separation. */
export function hashImageBytes(bytes: Buffer): string {
    return createHash('sha256').update(bytes).digest('base64url').slice(0, 22)
}

export function imageRef(teamId: number, hash: string): string {
    return `${PREFIX}:${teamId}:${hash}`
}

export function isImageRef(s: string): boolean {
    return REF_RE.test(s)
}

export function parseImageRef(s: string): { teamId: number; hash: string } | null {
    const m = REF_RE.exec(s)
    return m ? { teamId: Number(m[1]), hash: m[2] } : null
}
