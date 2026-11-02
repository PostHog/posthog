/** Image URL references of the v4 dataset. */
import { createHash } from 'crypto'

export type V4UrlAsset = 'image' | 'font'

export type V4UrlRef =
    | { scope: 'team'; asset: V4UrlAsset; teamId: number; keyMonth: string; hash: string }
    | { scope: 'public'; asset: 'font'; hash: string }

const HASH_CHARS = 22
const PUBLIC_FONT_HOST = 'fonts.gstatic.com'
const PUBLIC_FONT_PATH_PREFIX = '/s/'

function isRawTeamId(value: unknown): boolean {
    return typeof value === 'string' && /^[1-9][0-9]{0,15}$/.test(value) && Number.isSafeInteger(Number(value))
}

/** Parses `imageurl:v4:{team}:{YYYY-MM}:{hash}`, its `fonturl` twin and `fonturl:v4:public:{hash}`. `parseImageRef` refuses them all, so no v2 or v3 reader takes one. */
export function parseV4UrlRef(s: string): V4UrlRef | null {
    const shared = /^fonturl:v4:public:([A-Za-z0-9_-]{22})$/.exec(s)
    if (shared) {
        return { scope: 'public', asset: 'font', hash: shared[1] }
    }
    const match = /^(imageurl|fonturl):v4:([1-9][0-9]{0,15}):([0-9]{4}-(?:0[1-9]|1[0-2])):([A-Za-z0-9_-]{22})$/.exec(s)
    if (!match || !isRawTeamId(match[2])) {
        return null
    }
    return {
        scope: 'team',
        asset: match[1] === 'fonturl' ? 'font' : 'image',
        teamId: Number(match[2]),
        keyMonth: match[3],
        hash: match[4],
    }
}

export function urlAssetOf(originalRef: string): V4UrlAsset {
    return originalRef.startsWith('fonturl:') ? 'font' : 'image'
}

/** `replay_core_v4::refs::public_font_url_ref` for a canonical fetch URL. `encryption-vector-v4.json` pins both. */
export function publicFontRefOf(fetchUrl: string): string | undefined {
    let url: URL
    try {
        url = new URL(fetchUrl)
    } catch {
        return undefined
    }
    // WHATWG `search` is empty for a bare `?`, which the Rust url crate reads as an empty query.
    const shared =
        url.protocol === 'https:' &&
        url.hostname === PUBLIC_FONT_HOST &&
        url.port === '' &&
        url.pathname.startsWith(PUBLIC_FONT_PATH_PREFIX) &&
        !fetchUrl.includes('?')
    if (!shared) {
        return undefined
    }
    return `fonturl:v4:public:${createHash('sha256').update(fetchUrl).digest('base64url').slice(0, HASH_CHARS)}`
}
