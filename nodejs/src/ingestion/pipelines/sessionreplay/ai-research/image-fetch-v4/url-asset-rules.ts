import {
    FONT_MEDIA_TYPES,
    SUPPORTED_IMAGE_MEDIA_TYPES,
    prepareFetchedFont,
    prepareFetchedImage,
} from './image-transport'
import type { V4UrlAsset } from './v4-url-ref'

export interface UrlAssetRules {
    accept: string
    /** Media types the response may declare, lowercase and without parameters. */
    contentTypes: readonly string[]
    /** Decodes the response body and checks that its bytes are this asset, or throws `InvalidImageTransportError`. */
    prepare: (bytes: Buffer, contentType: string | undefined, contentEncoding: string | undefined) => Promise<Buffer>
    frameKind: 'image-url' | 'font-url'
    /** Each prefix needs a write grant for the fetcher's role in posthog-cloud-infra (`v4-staging.hcl`). */
    objectKeyPrefix: 'images/url' | 'fonts/url'
}

export const URL_ASSET_RULES: Record<V4UrlAsset, UrlAssetRules> = {
    image: {
        accept: 'image/*',
        contentTypes: SUPPORTED_IMAGE_MEDIA_TYPES,
        prepare: prepareFetchedImage,
        frameKind: 'image-url',
        objectKeyPrefix: 'images/url',
    },
    font: {
        accept: 'font/woff2, font/woff, font/ttf, font/otf, */*;q=0.1',
        contentTypes: FONT_MEDIA_TYPES,
        prepare: prepareFetchedFont,
        frameKind: 'font-url',
        objectKeyPrefix: 'fonts/url',
    },
}
