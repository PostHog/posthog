/** Media detection + placeholder/blur dispatch. */
import { BLANK_IMAGE_DATA_URI, blurImageDataUri, isImageDataUri, memoizedBlur } from './blur'
import { ScrubContext } from './config'
import { scrubUrl } from './url'

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

/**
 * Blur an inlined-image data URI held in an attribute (a `<canvas>`/`<img>` `rr_dataURL`).
 * Blanks it synchronously (fail-safe) and defers the real blur. Returns whether it acted.
 */
export function blurInlineImageAttr(ctx: ScrubContext, attrs: Record<string, unknown>, name: string): boolean {
    const value = attrs[name]
    if (typeof value !== 'string' || !isImageDataUri(value)) {
        return false
    }
    const original = value
    attrs[name] = BLANK_IMAGE_DATA_URI
    ctx.blurJobs?.push(async () => {
        const blurred = await memoizedBlur(ctx.blurCache, original, () => blurImageDataUri(original))
        if (blurred !== null) {
            attrs[name] = blurred
        }
    })
    return true
}

/** Replace a media element's source attrs with the placeholder (queuing a blur job for data-images). */
export function applyBlur(ctx: ScrubContext, attrs: Record<string, unknown>): void {
    for (const key of MEDIA_SRC_ATTRS) {
        const existing = attrs[key]
        if (typeof existing !== 'string') {
            continue
        }
        if (isImageDataUri(existing)) {
            attrs[key] = PLACEHOLDER_SRC
            ctx.blurJobs?.push(async () => {
                const blurred = await memoizedBlur(ctx.blurCache, existing, () => blurImageDataUri(existing))
                if (blurred !== null) {
                    attrs[key] = blurred
                }
            })
        } else {
            // Stash the scrubbed original under a namespaced attr (won't collide with app
            // `data-original-*`), host-scrubbed too so the CDN host can't leak.
            const scrubbed = scrubUrl(ctx, existing, { scrubAuthority: true })
            attrs[key] = PLACEHOLDER_SRC
            attrs[`data-anon-original-${key}`] = scrubbed.changed ? scrubbed.value : existing
        }
    }
}
