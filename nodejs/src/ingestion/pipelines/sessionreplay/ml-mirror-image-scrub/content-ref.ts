// The inline-image ref format shared by the producer, this consumer, and training joins.
// The hash uses a per-team HMAC, so the unencrypted bucket carries no unkeyed content digest.
// A plain sha256 would let a bucket reader confirm whether known bytes appeared in a session
// and correlate identical images across teams. The consumer trusts the producer (the only writer)
// and never recomputes the hash. The shared image-hash.json fixture pins the Rust construction.
// Legacy refs retain their team pseudonym so queued images still join to their replay blocks.
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
const CONTENT_REF_RE = /^image:([1-9][0-9]{0,15}|[0-9a-f]{32}):([A-Za-z0-9_-]{22})$/
const GLOBAL_URL_REF_RE = /^imageurl:([A-Za-z0-9_-]{22})$/
const LEGACY_URL_REF_RE = /^imageurl:([0-9a-f]{32}):([A-Za-z0-9_-]{22})$/

export function hashImageBytes(contentKey: string | Buffer, bytes: Buffer): string {
    return createHmac('sha256', contentKey).update(bytes).digest('base64url').slice(0, 22)
}

export function imageRef(teamId: string, hash: string): string {
    return `${PREFIX}:${teamId}:${hash}`
}

export function urlRef(hash: string): string {
    return `${URL_PREFIX}:${hash}`
}

export function isImageRef(s: string): boolean {
    return parseImageRef(s) !== null
}

export function isRawTeamId(value: unknown): boolean {
    return typeof value === 'string' && /^[1-9][0-9]{0,15}$/.test(value) && Number.isSafeInteger(Number(value))
}

/** Parses either kind of ref. `source` says which promise the hash carries. */
export function parseImageRef(
    s: string
): { teamId?: string; pseudoTeam?: string; hash: string; source: 'bytes' | 'url' } | null {
    const content = CONTENT_REF_RE.exec(s)
    if (content) {
        if (isRawTeamId(content[1])) {
            return { teamId: content[1], hash: content[2], source: 'bytes' }
        }
        return content[1].length === 32 ? { pseudoTeam: content[1], hash: content[2], source: 'bytes' } : null
    }
    const globalUrl = GLOBAL_URL_REF_RE.exec(s)
    if (globalUrl) {
        return { hash: globalUrl[1], source: 'url' }
    }
    const legacyUrl = LEGACY_URL_REF_RE.exec(s)
    return legacyUrl ? { pseudoTeam: legacyUrl[1], hash: legacyUrl[2], source: 'url' } : null
}
