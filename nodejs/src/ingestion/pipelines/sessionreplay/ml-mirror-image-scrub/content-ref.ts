// The shared ref format between the producer, this consumer, and training joins; pseudo_team is the
// non-reversible HMAC team pseudonym from ml-mirror/pseudonymize.ts (keeps raw team ids out of the
// ML bucket). The hash half is keyed (per-team HMAC, derived alongside the pseudonym) so the
// unencrypted bucket carries no unkeyed content digest — a plain sha256 would let a bucket reader
// confirm whether specific known bytes appeared in a session, and correlate identical images across
// teams. The consumer trusts the producer's ref (it is the only writer) and never recomputes the
// hash; the Rust producer implementation is pinned to this one by the shared image-hash.json fixture.
import { createHmac } from 'node:crypto'

const PREFIX = 'image'
const REF_RE = /^image:([0-9a-f]{32}):([A-Za-z0-9_-]{22})$/

export function hashImageBytes(contentKey: string | Buffer, bytes: Buffer): string {
    return createHmac('sha256', contentKey).update(bytes).digest('base64url').slice(0, 22)
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
