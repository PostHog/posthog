/**
 * How the ml-mirror producer handles an inlined replay image.
 *  - 'passthrough': untouched. Only below the detector floor (<=16px), where no face/text is findable, so
 *    scrubbing loses zero protection while destroying high-signal icons/logos/glyphs useful for training.
 *  - 'cheapBlur': in-process downsample+blur. For canvas (dynamic, ~no dedup, so the advanced path would
 *    flood the topic + S3 with non-deduping frames) and for images too big for the topic.
 *  - 'advancedScrub': hash -> Redis dedup -> scrub topic -> consumer scrubs and writes to S3. For static
 *    <img>/media raster, which dedups well (logos/avatars/photos) and is PII-bearing.
 */
export type ImageSource = 'canvas' | 'img' | 'media'
export type ScrubMethod = 'passthrough' | 'cheapBlur' | 'advancedScrub'

export const TINY_MAX_SIDE = 16 // <= this on the long side => below the face/text detector floor
// A genuine <=16px image is a few hundred bytes. Secondary guard backstopping a malformed image whose
// header a parser might misread as tiny (dimensions come from the header, not spoofable rrweb attrs).
export const TINY_MAX_BYTES = 4096
export const TOPIC_MAX_BYTES = 900_000 // under Kafka's ~1MB message cap, leaving room for the envelope

export interface ImageMetadata {
    source: ImageSource
    /** Pixel dimensions if known (from rrweb attrs or a header decode); omit if unknown. */
    width?: number
    height?: number
    /** Size of the raw (decoded-from-base64) image bytes. */
    byteLength: number
}

export function getScrubMethodForImage(i: ImageMetadata): ScrubMethod {
    // Passthrough requires both header dimensions and byte size tiny; unknown dimensions => scrubbed.
    if (
        i.width != null &&
        i.height != null &&
        Math.max(i.width, i.height) <= TINY_MAX_SIDE &&
        i.byteLength <= TINY_MAX_BYTES
    ) {
        return 'passthrough'
    }
    // Canvas dedups ~never, so blur it rather than flood the topic.
    if (i.source === 'canvas') {
        return 'cheapBlur'
    }
    // Too big for the topic (rare; capture drops >~1MB already).
    if (i.byteLength > TOPIC_MAX_BYTES) {
        return 'cheapBlur'
    }
    return 'advancedScrub'
}
