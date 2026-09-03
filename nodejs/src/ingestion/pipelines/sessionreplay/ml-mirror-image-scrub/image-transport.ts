import { Readable, Transform } from 'node:stream'
import { createBrotliDecompress, createGunzip, createInflate, createZstdDecompress } from 'node:zlib'

export const MAX_UNCOMPRESSED_IMAGE_BYTES = 20 * 1024 * 1024
export const CONTENT_TYPE_HEADER = 'content-type'
export const CONTENT_ENCODING_HEADER = 'content-encoding'
export const CAPTURE_TIMESTAMP_HEADER = 'capture-timestamp-ms'

const MAX_CONTENT_ENCODING_LAYERS = 4

export const SUPPORTED_IMAGE_MEDIA_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif'] as const

export type SupportedImageMediaType = (typeof SUPPORTED_IMAGE_MEDIA_TYPES)[number]

export type ImageTransportRejectionReason =
    | 'content_encoding_too_deep'
    | 'malformed_content_encoding'
    | 'unsupported_content_encoding'
    | 'decompression_failed'
    | 'decoded_too_large'
    | 'missing_content_type'
    | 'unsupported_content_type'
    | 'content_type_mismatch'

export class InvalidImageTransportError extends Error {
    public constructor(
        public readonly reason: ImageTransportRejectionReason,
        message: string
    ) {
        super(message)
    }
}

const decoderFactories: Record<string, () => Transform> = {
    gzip: createGunzip,
    deflate: createInflate,
    br: createBrotliDecompress,
    zstd: createZstdDecompress,
}

function parseContentEncodings(contentEncoding: string | undefined): string[] {
    if (contentEncoding === undefined) {
        return []
    }
    const encodings = contentEncoding.split(',').map((encoding) => encoding.trim().toLowerCase())
    if (encodings.length > MAX_CONTENT_ENCODING_LAYERS) {
        throw new InvalidImageTransportError(
            'content_encoding_too_deep',
            `content-encoding exceeds ${MAX_CONTENT_ENCODING_LAYERS} codings`
        )
    }
    if (encodings.some((encoding) => encoding.length === 0)) {
        throw new InvalidImageTransportError('malformed_content_encoding', 'content-encoding contains an empty coding')
    }
    return encodings.filter((encoding) => encoding !== 'identity')
}

async function decodeWithLimit(bytes: Buffer, encoding: string): Promise<Buffer> {
    const decoderFactory = decoderFactories[encoding]
    if (!decoderFactory) {
        throw new InvalidImageTransportError(
            'unsupported_content_encoding',
            `unsupported content-encoding: ${encoding}`
        )
    }

    const input = Readable.from([bytes])
    const decoder = decoderFactory()
    const chunks: Buffer[] = []
    let outputBytes = 0
    input.pipe(decoder)

    try {
        for await (const chunk of decoder) {
            const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
            if (outputBytes + buffer.length > MAX_UNCOMPRESSED_IMAGE_BYTES) {
                throw new InvalidImageTransportError(
                    'decoded_too_large',
                    `decoded image exceeds ${MAX_UNCOMPRESSED_IMAGE_BYTES} bytes`
                )
            }
            chunks.push(buffer)
            outputBytes += buffer.length
        }
    } catch (error) {
        if (error instanceof InvalidImageTransportError) {
            throw error
        }
        throw new InvalidImageTransportError('decompression_failed', `invalid ${encoding} content: ${String(error)}`)
    } finally {
        input.destroy()
        decoder.destroy()
    }

    return Buffer.concat(chunks, outputBytes)
}

function isAvif(bytes: Buffer): boolean {
    if (bytes.length < 16 || bytes.toString('ascii', 4, 8) !== 'ftyp') {
        return false
    }
    const boxSize = bytes.readUInt32BE(0)
    if (boxSize < 16 || boxSize > bytes.length) {
        return false
    }
    for (let offset = 8; offset + 4 <= boxSize; offset += 4) {
        const brand = bytes.toString('ascii', offset, offset + 4)
        if (brand === 'avif' || brand === 'avis') {
            return true
        }
    }
    return false
}

export function isSupportedImageMediaType(contentType: string): contentType is SupportedImageMediaType {
    return SUPPORTED_IMAGE_MEDIA_TYPES.includes(contentType as SupportedImageMediaType)
}

export function imageBytesMatchMediaType(bytes: Buffer, contentType: SupportedImageMediaType): boolean {
    switch (contentType) {
        case 'image/png':
            return bytes.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))
        case 'image/jpeg':
            return bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff
        case 'image/gif': {
            const signature = bytes.toString('ascii', 0, 6)
            return signature === 'GIF87a' || signature === 'GIF89a'
        }
        case 'image/webp':
            return bytes.toString('ascii', 0, 4) === 'RIFF' && bytes.toString('ascii', 8, 12) === 'WEBP'
        case 'image/avif':
            return isAvif(bytes)
    }
}

export async function prepareFetchedImage(
    bytes: Buffer,
    contentType: string | undefined,
    contentEncoding: string | undefined
): Promise<Buffer> {
    if (!contentType) {
        throw new InvalidImageTransportError('missing_content_type', 'unsupported content-type: missing')
    }
    if (!isSupportedImageMediaType(contentType)) {
        throw new InvalidImageTransportError('unsupported_content_type', `unsupported content-type: ${contentType}`)
    }
    if (bytes.length > MAX_UNCOMPRESSED_IMAGE_BYTES) {
        throw new InvalidImageTransportError(
            'decoded_too_large',
            `decoded image exceeds ${MAX_UNCOMPRESSED_IMAGE_BYTES} bytes`
        )
    }

    let decoded = bytes
    const encodings = parseContentEncodings(contentEncoding)
    for (const encoding of encodings.reverse()) {
        decoded = await decodeWithLimit(decoded, encoding)
    }
    if (!imageBytesMatchMediaType(decoded, contentType)) {
        throw new InvalidImageTransportError(
            'content_type_mismatch',
            `image bytes do not match content-type ${contentType}`
        )
    }
    return decoded
}
