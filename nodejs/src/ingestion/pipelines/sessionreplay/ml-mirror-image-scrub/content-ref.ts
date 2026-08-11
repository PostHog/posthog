// The shared ref format between the producer, this consumer, and training joins; pseudo_team is the
// non-reversible HMAC team pseudonym from ml-mirror/pseudonymize.ts (keeps raw team ids out of the
// ML bucket). The hash half is keyed (per-team HMAC, derived alongside the pseudonym) so the
// unencrypted bucket carries no unkeyed content digest — a plain sha256 would let a bucket reader
// confirm whether specific known bytes appeared in a session, and correlate identical images across
// teams. The consumer trusts the producer's ref (it is the only writer) and never recomputes the
// hash; the Rust producer implementation is pinned to this one by the shared image-hash.json fixture.
import { createHmac } from 'node:crypto'

const PREFIX = 'image'
/**
 * The prefix of a ref whose hash names a URL rather than the bytes behind it.
 *
 * A content ref promises the hash names the bytes, which is what lets a reader treat one as
 * content-addressed. The bytes at a URL can change, so a URL ref cannot make that promise. One
 * prefix for both would leave a reader unable to tell which it holds, and the failure would be a
 * silent mis-join rather than an error.
 */
const URL_PREFIX = 'imageurl'
const REF_RE = /^(image|imageurl):([0-9a-f]{32}):([A-Za-z0-9_-]{22})$/

export function hashImageBytes(contentKey: string | Buffer, bytes: Buffer): string {
    return createHmac('sha256', contentKey).update(bytes).digest('base64url').slice(0, 22)
}

export function imageRef(pseudoTeam: string, hash: string): string {
    return `${PREFIX}:${pseudoTeam}:${hash}`
}

export function urlRef(pseudoTeam: string, hash: string): string {
    return `${URL_PREFIX}:${pseudoTeam}:${hash}`
}

export function isImageRef(s: string): boolean {
    return REF_RE.test(s)
}

/** Parses either kind of ref. `source` says which promise the hash carries. */
export function parseImageRef(s: string): { pseudoTeam: string; hash: string; source: 'bytes' | 'url' } | null {
    const m = REF_RE.exec(s)
    return m ? { pseudoTeam: m[2], hash: m[3], source: m[1] === PREFIX ? 'bytes' : 'url' } : null
}
