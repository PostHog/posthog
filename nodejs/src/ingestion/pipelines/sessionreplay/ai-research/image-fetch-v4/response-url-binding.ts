import { createHmac, hkdfSync } from 'node:crypto'

import type {
    TeamMonthKey,
    TeamMonthKeys,
} from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/team-month-keys'

import { parseV4UrlRef } from './v4-url-ref'

/** The HKDF info of `replay_core_v4::seal::image_url_key`, the key behind the hash of an `imageurl:v4` reference. */
const IMAGE_URL_KEY_INFO = 'ml-image-url-key'
/** The length `replay_core_v4::refs::reference_hash` truncates a hash to. */
const HASH_CHARS = 22

/** The keyed hash that the crawl history stores in place of a response URL. */
export type ResponseUrlBinding = (url: string) => string

export interface ResponseUrlBinder {
    bindingFor(originalRef: string, signal: AbortSignal): Promise<ResponseUrlBinding | undefined>
}

/**
 * Binds cached validators to the URL that issued them without storing that URL, which can hold personal data. The
 * binding is the HMAC of the URL under the image URL key of the reference's team month, so it compares only within
 * that team month. A reference with no live key has no binding, and its fetch sends no validators.
 */
export class TeamMonthResponseUrlBinder implements ResponseUrlBinder {
    constructor(private readonly keys: Pick<TeamMonthKeys, 'get'>) {}

    public async bindingFor(originalRef: string, signal: AbortSignal): Promise<ResponseUrlBinding | undefined> {
        const ref = parseV4UrlRef(originalRef)
        if (!ref) {
            return undefined
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
        const urlKey = Buffer.from(hkdfSync('sha256', key.key, Buffer.alloc(0), IMAGE_URL_KEY_INFO, 32))
        return (url) => createHmac('sha256', urlKey).update(url).digest('base64url').slice(0, HASH_CHARS)
    }
}
