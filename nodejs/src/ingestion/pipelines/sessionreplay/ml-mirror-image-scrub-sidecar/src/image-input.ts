import sharp, { type Sharp } from 'sharp'

import { imageMetadataProhibitsAiTraining } from './xmp.ts'

// One libvips thread per operation and no shared cache bound CPU and memory to the request concurrency limit.
sharp.concurrency(1)
sharp.cache(false)
// The lane accepts only PNG, JPEG, GIF and WebP, so every other loader is blocked. An allowlist also covers a loader
// that a later libvips build adds. Blocking or unblocking a class applies to its buffer, file and source subclasses,
// so any other input, such as TIFF, AVIF, HEIC or SVG, fails as an unsupported format. The UltraHDR loader stays
// blocked, so a JPEG with a gain map decodes through the JPEG loader, which ignores the gain map.
sharp.block({ operation: ['VipsForeignLoad'] })
sharp.unblock({
    operation: ['VipsForeignLoadPng', 'VipsForeignLoadJpeg', 'VipsForeignLoadNsgif', 'VipsForeignLoadWebp'],
})

// Compressed image bytes can expand many times in memory, so every decoder applies this pixel limit before allocation.
export const LIMIT_INPUT_PIXELS = 50_000_000

export class PermanentImageError extends Error {}
export type UndecodableImageReason =
    | 'decode_failed'
    | 'invalid_body'
    | 'invalid_dimensions'
    | 'pixel_limit'
    | 'unsupported_format'

export class UndecodableImageError extends PermanentImageError {
    public constructor(
        public readonly reason: UndecodableImageReason,
        message: string
    ) {
        super(message)
    }
}
export class ImageOptOutError extends PermanentImageError {}

export function undecodableImageErrorFromDecodeFailure(error: unknown): UndecodableImageError {
    const message = error instanceof Error ? error.message : String(error)
    const normalizedMessage = message.toLowerCase()
    const reason = normalizedMessage.includes('pixel limit')
        ? 'pixel_limit'
        : normalizedMessage.includes('unsupported image format')
          ? 'unsupported_format'
          : 'decode_failed'
    return new UndecodableImageError(reason, message)
}

export interface ImageDescription {
    width: number
    height: number
    format: string
}

export async function inspectImage(input: Buffer): Promise<ImageDescription> {
    const metadata = await sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS }).metadata()
    if (!metadata.width || !metadata.height) {
        throw new UndecodableImageError('invalid_dimensions', 'image has invalid dimensions')
    }
    if (metadata.width * metadata.height > LIMIT_INPUT_PIXELS) {
        throw new UndecodableImageError('pixel_limit', 'image exceeds the pixel limit')
    }
    if (imageMetadataProhibitsAiTraining(input, metadata.xmp)) {
        throw new ImageOptOutError('image metadata prohibits AI training')
    }
    return {
        width: metadata.width,
        height: metadata.height,
        format: metadata.format ?? 'unknown',
    }
}

export function sharpForImage(input: Buffer): Sharp {
    return sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS })
}
