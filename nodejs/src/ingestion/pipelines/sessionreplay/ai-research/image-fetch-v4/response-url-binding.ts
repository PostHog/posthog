import type {
    TeamMonthKey,
    TeamMonthKeys,
} from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/team-month-keys'

import { imageUrlHash, parseV4UrlRef, publicUrlHash } from './v4-native'

/** The keyed hash that the crawl history stores in place of a response URL. */
export type ResponseUrlBinding = (url: string) => string

export interface ResponseUrlBinder {
    bindingFor(originalRef: string, signal: AbortSignal): Promise<ResponseUrlBinding | undefined>
}

/**
 * Binds cached validators to the URL that issued them without storing that URL, which can hold personal data. The
 * binding is the HMAC of the URL under the image URL key of the reference's team month, so it compares only within
 * that team month. A reference with no live key has no binding, and its fetch sends no validators.
 * A public font's URL holds no personal data, so its binding is the unkeyed hash that its reference uses.
 */
export class TeamMonthResponseUrlBinder implements ResponseUrlBinder {
    constructor(private readonly keys: Pick<TeamMonthKeys, 'get'>) {}

    public async bindingFor(originalRef: string, signal: AbortSignal): Promise<ResponseUrlBinding | undefined> {
        const ref = parseV4UrlRef(originalRef)
        if (!ref) {
            return undefined
        }
        if (ref.scope === 'public') {
            return publicUrlHash
        }
        let key: TeamMonthKey
        try {
            key = await this.keys.get(ref.teamId, ref.keyMonth, signal)
        } catch {
            // Admission read this key moments ago, so a failure here costs one revalidation and not the fetch.
            return undefined
        }
        if (key.status !== 'ok') {
            return undefined
        }
        const teamMonthKey = key.key
        return (url) => imageUrlHash(teamMonthKey, url)
    }
}
