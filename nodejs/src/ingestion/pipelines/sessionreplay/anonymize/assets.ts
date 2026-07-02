/** Media detection + placeholder/blur dispatch. */
import { imageSize } from 'image-size'

import {
    ImageSource,
    getScrubMethodForImage,
} from '~/ingestion/pipelines/sessionreplay/ml-mirror/image-scrub/scrub-method'

import { BLANK_IMAGE_DATA_URI, blurImageBytes, isImageDataUri, memoizedBlur } from './blur'
import { ScrubContext } from './config'
import { scrubUrl } from './url'

// Bound per-message hand-off to the topic so an outlier session with many large images can't pin unbounded memory across the emit; overflow falls back to cheap blur.
const MAX_ADVANCED_IMAGES_PER_MESSAGE = 64
const MAX_ADVANCED_BYTES_PER_MESSAGE = 32 * 1024 * 1024 // 32 MB

// rrweb inlines rendered pixels (a `toDataURL()` snapshot) into this attribute — for `<canvas>`
// in a FullSnapshot/adds, and for `<img>` when image inlining is on. It holds raw drawn content.
export const INLINE_IMAGE_ATTR = 'rr_dataURL'

export const PLACEHOLDER_SRC =
    "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 80 80'><rect width='80' height='80' fill='%23f3f4f6'/><rect x='6' y='6' width='68' height='68' fill='none' stroke='%23d1d5db' stroke-width='2' rx='6'/><circle cx='26' cy='26' r='6' fill='%239ca3af'/><path d='M14 60 L34 40 L48 50 L66 32 L66 66 L14 66 Z' fill='%239ca3af'/></svg>"

export const MEDIA_SRC_ATTRS = ['src', 'srcset', 'href', 'xlink:href', 'poster']

export function isMediaTag(tag: string): boolean {
    switch (tag.toLowerCase()) {
        case 'img':
        case 'image':
        case 'video':
        case 'audio':
        case 'source':
        case 'track':
        case 'picture':
            return true
        default:
            return false
    }
}

export function isMediaSrcAttr(name: string): boolean {
    return MEDIA_SRC_ATTRS.includes(name)
}

/** True if an attribute map contains any media-source attribute. */
export function hasMediaSrcAttr(attrs: Record<string, unknown>): boolean {
    return MEDIA_SRC_ATTRS.some((name) => Object.prototype.hasOwnProperty.call(attrs, name))
}

/** Raw bytes of an image data URI's base64 payload, or null if not a base64 image data URI. Format is
 *  NOT validated here on purpose: magic-byte filtering would risk false-rejecting a real but unlisted
 *  format (e.g. AVIF), which leaves the raw image inline (a PII leak); the consumer's sharp decode is
 *  the authority on "real image" instead. */
function imageDataUriBytes(dataUri: string): Buffer | null {
    const comma = dataUri.indexOf(',')
    if (comma < 0) {
        return null
    }
    const meta = dataUri.slice('data:'.length, comma)
    if (!meta.includes('base64') || !meta.startsWith('image/')) {
        return null
    }
    return Buffer.from(dataUri.slice(comma + 1), 'base64')
}

/** Intrinsic pixel dimensions from the image header (sync, header-only), or undefined if unreadable,
 *  which routes to scrubbing (fail-closed) so a crafted/undecodable image is never passed through. NOT
 *  the rrweb width/height attrs: those are display size (spoofable; a large image can be shown at 16px). */
function imageDimensions(bytes: Buffer): { width: number; height: number } | undefined {
    try {
        const { width, height } = imageSize(bytes)
        return typeof width === 'number' && typeof height === 'number' ? { width, height } : undefined
    } catch {
        return undefined
    }
}

/** Route one inlined image in `attrs[name]` per getScrubMethodForImage: advancedScrub collects the
 *  bytes for the topic (placeholder now, reference written in place after the emit), cheapBlur defers an
 *  in-process blur, passthrough leaves it. Returns whether it acted. */
function scrubInlineImage(
    ctx: ScrubContext,
    attrs: Record<string, unknown>,
    name: string,
    source: ImageSource,
    placeholder: string
): boolean {
    const value = attrs[name]
    if (typeof value !== 'string' || !isImageDataUri(value)) {
        return false
    }
    // SVGs always pass through untouched: they're vector UI assets (icons, logos, chrome), not the
    // photographic raster the face/blur scrubbers target, and rasterizing one to blur it would destroy
    // high-signal vector training data while protecting nothing those scrubbers are for.
    if (/^data:image\/svg/i.test(value)) {
        return false
    }
    const bytes = imageDataUriBytes(value)
    if (bytes === null) {
        return false
    }
    const dims = imageDimensions(bytes)
    const scrubMethod = getScrubMethodForImage({
        source,
        width: dims?.width,
        height: dims?.height,
        byteLength: bytes.length,
    })
    if (scrubMethod === 'passthrough') {
        return false
    }
    const jobs = ctx.imageScrubJobs
    const underCap =
        jobs != null &&
        jobs.length < MAX_ADVANCED_IMAGES_PER_MESSAGE &&
        jobs.reduce((n, j) => n + j.bytes.length, bytes.length) <= MAX_ADVANCED_BYTES_PER_MESSAGE
    if (scrubMethod === 'advancedScrub' && ctx.imageScrub && ctx.teamId != null && jobs != null && underCap) {
        attrs[name] = placeholder // fail-safe until the reference is written in place after the emit
        jobs.push({
            bytes,
            apply: (ref) => {
                attrs[name] = ref
            },
        })
        return true
    }
    // cheapBlur: canvas/oversize, ports/team absent, or over the per-message cap. Reuses the decoded bytes (no second base64 decode).
    attrs[name] = placeholder
    ctx.blurJobs?.push(async () => {
        // Memoize by the data-URI string so an image recurring across the message's rrweb events blurs once; reuses the already-decoded bytes.
        const blurred = await memoizedBlur(ctx.blurCache, value, () => blurImageBytes(bytes))
        if (blurred !== null) {
            attrs[name] = blurred
        }
    })
    return true
}

/**
 * Scrub an inlined-image data URI held in an attribute (a `<canvas>`/`<img>` `rr_dataURL`). Canvas is
 * dynamic (routed cheap); a static <img>'s inline pixels take the advanced topic path when wired.
 * Returns whether it acted.
 */
export function blurInlineImageAttr(
    ctx: ScrubContext,
    attrs: Record<string, unknown>,
    name: string,
    source: ImageSource = 'canvas'
): boolean {
    return scrubInlineImage(ctx, attrs, name, source, BLANK_IMAGE_DATA_URI)
}

/** Replace a media element's source attrs with the placeholder (routing inline data-images to the
 *  scrub topic or the in-process blur; remote srcs are host+path scrubbed and stashed). */
export function applyBlur(ctx: ScrubContext, attrs: Record<string, unknown>): void {
    for (const key of MEDIA_SRC_ATTRS) {
        const existing = attrs[key]
        if (typeof existing !== 'string') {
            continue
        }
        if (isImageDataUri(existing)) {
            scrubInlineImage(ctx, attrs, key, 'media', PLACEHOLDER_SRC)
        } else {
            // Stash the scrubbed original under a namespaced attr (won't collide with app
            // `data-original-*`), host-scrubbed too so the CDN host can't leak.
            const scrubbed = scrubUrl(ctx, existing, { scrubAuthority: true })
            attrs[key] = PLACEHOLDER_SRC
            attrs[`data-anon-original-${key}`] = scrubbed.changed ? scrubbed.value : existing
        }
    }
}
