/** Image and font URL references of the v4 dataset. */

export type V4UrlAsset = 'image' | 'font'

function isRawTeamId(value: unknown): boolean {
    return typeof value === 'string' && /^[1-9][0-9]{0,15}$/.test(value) && Number.isSafeInteger(Number(value))
}

/**
 * Parses `imageurl:v4:{team}:{YYYY-MM}:{hash}` and `fonturl:v4:{team}:{YYYY-MM}:{hash}`. `parseImageRef` refuses both,
 * so no v2 or v3 reader takes one.
 */
export function parseV4UrlRef(s: string): { asset: V4UrlAsset; teamId: number; keyMonth: string; hash: string } | null {
    const match = /^(imageurl|fonturl):v4:([1-9][0-9]{0,15}):([0-9]{4}-(?:0[1-9]|1[0-2])):([A-Za-z0-9_-]{22})$/.exec(s)
    if (!match || !isRawTeamId(match[2])) {
        return null
    }
    return {
        asset: match[1] === 'fonturl' ? 'font' : 'image',
        teamId: Number(match[2]),
        keyMonth: match[3],
        hash: match[4],
    }
}

/** The asset of a reference that `parseV4UrlRef` accepted. */
export function urlAssetOf(originalRef: string): V4UrlAsset {
    return originalRef.startsWith('fonturl:') ? 'font' : 'image'
}
