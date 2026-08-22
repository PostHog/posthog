import { decode as decodeBmp } from 'bmp-ts'
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

function isBmp(input: Buffer): boolean {
    return input.toString('ascii', 0, 2) === 'BM'
}

function inspectBmp(input: Buffer): ImageDescription {
    if (input.length < 54) {
        throw new UndecodableImageError('BMP header is truncated')
    }
    const headerSize = input.readUInt32LE(14)
    if (headerSize < 40) {
        throw new UndecodableImageError(`unsupported BMP header size ${headerSize}`)
    }
    const pixelOffset = input.readUInt32LE(10)
    if (14 + headerSize > input.length || pixelOffset < 14 + headerSize || pixelOffset > input.length) {
        throw new UndecodableImageError('BMP has invalid header bounds')
    }
    const compression = input.readUInt32LE(30)
    if (compression !== 0) {
        throw new UndecodableImageError(`unsupported BMP compression ${compression}`)
    }
    const width = input.readInt32LE(18)
    const signedHeight = input.readInt32LE(22)
    const height = Math.abs(signedHeight)
    if (width <= 0 || height === 0) {
        throw new UndecodableImageError('BMP has invalid dimensions')
    }
    if (!Number.isSafeInteger(width * height) || width * height > LIMIT_INPUT_PIXELS) {
        throw new UndecodableImageError('image exceeds the pixel limit')
    }
    const planes = input.readUInt16LE(26)
    const bitsPerPixel = input.readUInt16LE(28)
    if (planes !== 1 || ![1, 4, 8, 16, 24, 32].includes(bitsPerPixel)) {
        throw new UndecodableImageError('BMP has an unsupported pixel layout')
    }
    const paletteEntries = input.readUInt32LE(46) || (bitsPerPixel <= 8 ? 2 ** bitsPerPixel : 0)
    if (paletteEntries > 256 || paletteEntries * 4 > pixelOffset - (14 + headerSize)) {
        throw new UndecodableImageError('BMP has invalid palette bounds')
    }
    return { width, height, format: 'bmp' }
}

export async function inspectImage(input: Buffer): Promise<ImageDescription> {
    if (isBmp(input)) {
        return inspectBmp(input)
    }
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

export function sharpForImage(input: Buffer, description: ImageDescription): Sharp {
    if (description.format !== 'bmp') {
        return sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS })
    }
    const decoded = decodeBmp(input, { toRGBA: true })
    if (
        decoded.width !== description.width ||
        decoded.height !== description.height ||
        decoded.data.length !== description.width * description.height * 4
    ) {
        throw new UndecodableImageError('decoded BMP dimensions do not match its header')
    }
    if (decoded.bitPP < 32) {
        // bmp-ts emits zero alpha for BMP depths that have no alpha channel, which would flatten every pixel to white.
        for (let alphaOffset = 3; alphaOffset < decoded.data.length; alphaOffset += 4) {
            decoded.data[alphaOffset] = 0xff
        }
    }
    return sharp(decoded.data, {
        raw: { width: description.width, height: description.height, channels: 4 },
    })
}
