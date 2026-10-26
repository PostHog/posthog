/** Image URL references of the v4 dataset. */

function isRawTeamId(value: unknown): boolean {
    return typeof value === 'string' && /^[1-9][0-9]{0,15}$/.test(value) && Number.isSafeInteger(Number(value))
}

/** Parses `imageurl:v4:{team}:{YYYY-MM}:{hash}`. `parseImageRef` refuses it, so no v2 or v3 reader takes one. */
export function parseV4UrlRef(s: string): { teamId: number; keyMonth: string; hash: string } | null {
    const match = /^imageurl:v4:([1-9][0-9]{0,15}):([0-9]{4}-(?:0[1-9]|1[0-2])):([A-Za-z0-9_-]{22})$/.exec(s)
    if (!match || !isRawTeamId(match[1])) {
        return null
    }
    return { teamId: Number(match[1]), keyMonth: match[2], hash: match[3] }
}
