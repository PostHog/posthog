import { createHmac } from 'crypto'

export function pseudonymize(secret: string | Buffer, namespace: string, value: string): string {
    // Length-prefix the namespace so the join is unambiguous even if a value contains the delimiter.
    return createHmac('sha256', secret).update(`${namespace.length}:${namespace}:${value}`).digest('hex').slice(0, 32)
}

/** Namespace for the per-team image content-HMAC key (see ml-mirror-image-scrub/content-ref.ts). */
export const PSEUDONYM_IMAGE_CONTENT_KEY = 'image-content-key'
/** Namespace for the global URL-HMAC key, which hashes a remote image's URL rather than its bytes. */
export const PSEUDONYM_IMAGE_URL_KEY = 'image-url-key'
export const PSEUDONYM_IMAGE_URL_GLOBAL_VALUE = 'global-v1'

export const PSEUDONYM_TEAM = 'team'
export const PSEUDONYM_SESSION = 'session'
export const PSEUDONYM_DISTINCT_ID = 'distinct_id'
