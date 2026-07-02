/**
 * Content reference for an inlined replay image: the ml-mirror producer (this side) swaps the raw
 * `rr_dataURL` for one of these, the consumer writes the scrubbed image to S3 under the same reference,
 * and training resolves block -> image by it. Format `image:{team_id}:{hash}`, hash = 132-bit sha256,
 * base64url, 22 chars. The team_id prefix is load-bearing: it scopes dedup and S3 storage per team, so
 * identical bytes in two teams produce two references and never share a scrubbed object.
 *
 * CONTRACT: must stay byte-identical to the consumer's copy at
 * products/replay_vision/services/ml-mirror-image-scrub/src/content-ref.ts or references won't resolve.
 * Both sides assert the same hardcoded golden vector (input -> hash/ref), image-scrub.test.ts here and
 * dev/content-ref.test.ts there, so a unilateral change fails its own test; change them together. Stage 2
 * should extract a shared package and delete this duplicate.
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
