import {
    FONT_MEDIA_TYPES,
    SUPPORTED_IMAGE_MEDIA_TYPES,
    imageBytesMatchMediaType,
    isFontFile,
    isSupportedImageMediaType,
    prepareFetchedFont,
    prepareFetchedImage,
} from './image-transport'
import type { V4UrlAsset } from './v4-native'

export interface UrlAssetRules {
    accept: string
    contentTypes: readonly string[]
    prepare: (bytes: Buffer, contentType: string | undefined, contentEncoding: string | undefined) => Promise<Buffer>
    /** From the first `SIGNATURE_BYTES` of a body with no content coding. It must accept every body `prepare` accepts. */
    canStartWith: (head: Buffer, contentType: string) => boolean
    /** Each prefix needs a write grant for the fetcher's role in posthog-cloud-infra (`v4-staging.hcl`). */
    objectKeyPrefix: 'images/url' | 'fonts/url'
}

export const URL_ASSET_RULES: Record<V4UrlAsset, UrlAssetRules> = {
    image: {
        // An image CDN that picks a format from this header looks for WebP by name, and sends the original otherwise.
        accept: 'image/webp,image/*;q=0.8',
        contentTypes: SUPPORTED_IMAGE_MEDIA_TYPES,
        prepare: prepareFetchedImage,
        // SVG has no signature, and its check reads far more than the first bytes.
        canStartWith: (head, contentType) =>
            !isSupportedImageMediaType(contentType) ||
            contentType === 'image/svg+xml' ||
            imageBytesMatchMediaType(head, contentType),
        objectKeyPrefix: 'images/url',
    },
    font: {
        accept: 'font/woff2, font/woff, font/ttf, font/otf, */*;q=0.1',
        contentTypes: FONT_MEDIA_TYPES,
        prepare: prepareFetchedFont,
        canStartWith: (head) => isFontFile(head),
        objectKeyPrefix: 'fonts/url',
    },
}
