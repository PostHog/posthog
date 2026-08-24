import sharp, { type Sharp } from 'sharp'

import { imageMetadataProhibitsAiTraining } from './xmp.ts'

// One libvips thread per operation and no shared cache bound CPU and memory to the request concurrency limit.
sharp.concurrency(1)
sharp.cache(false)
// The accepted image types do not need TIFF or native VIPS loaders, so blocking them removes unnecessary decoder paths.
sharp.block({ operation: ['VipsForeignLoadTiff', 'VipsForeignLoadVips'] })

// Compressed image bytes can expand many times in memory, so every decoder applies this pixel limit before allocation.
export const LIMIT_INPUT_PIXELS = 50_000_000

export class PermanentImageError extends Error {}
export class UndecodableImageError extends PermanentImageError {}
export class ImageOptOutError extends PermanentImageError {}

export interface ImageDescription {
    width: number
    height: number
    format: string
}

export async function inspectImage(input: Buffer): Promise<ImageDescription> {
    const metadata = await sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS }).metadata()
    if (!metadata.width || !metadata.height) {
        throw new UndecodableImageError('image has invalid dimensions')
    }
    if (metadata.width * metadata.height > LIMIT_INPUT_PIXELS) {
        throw new UndecodableImageError('image exceeds the pixel limit')
    }
    if (imageMetadataProhibitsAiTraining(input, metadata.xmp)) {
        throw new ImageOptOutError('image metadata prohibits AI training')
    }
    return {
        width: metadata.width,
        height: metadata.height,
        format: metadata.format === 'heif' ? 'avif' : (metadata.format ?? 'unknown'),
    }
}

export function sharpForImage(input: Buffer): Sharp {
    return sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS })
}
