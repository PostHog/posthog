import { Readable, Transform } from 'node:stream'
import { createBrotliDecompress, createGunzip, createInflate, createZstdDecompress } from 'node:zlib'

export const MAX_UNCOMPRESSED_IMAGE_BYTES = 20 * 1024 * 1024
export const CONTENT_TYPE_HEADER = 'content-type'
export const CONTENT_ENCODING_HEADER = 'content-encoding'

const MAX_CONTENT_ENCODING_LAYERS = 4

/** Keep in step with `FETCHED_IMAGE_TYPES` in `replay-core-v4/src/url_policy.rs`, which tells the recorder what this lane stores. */
export const SUPPORTED_IMAGE_MEDIA_TYPES = [
    'image/png',
    'image/jpeg',
    'image/gif',
    'image/webp',
    'image/svg+xml',
] as const

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

const ZSTD_FRAME_MAGIC = 0xfd2fb528

/**
 * Node's zstd decoder ends without an error on a truncated frame, and it drops every frame after the first. Both give a
 * prefix of the image. So this walks the frame and block headers of RFC 8878 and accepts exactly one frame that ends
 * at the last byte, as the Rust recorder's `unzstd` does.
 */
function isSingleCompleteZstdFrame(bytes: Buffer): boolean {
    if (bytes.length < 5 || bytes.readUInt32LE(0) !== ZSTD_FRAME_MAGIC) {
        return false
    }
    const descriptor = bytes[4]
    const singleSegment = (descriptor & 0x20) !== 0
    const contentSizeFlag = descriptor >> 6
    const windowBytes = singleSegment ? 0 : 1
    const dictionaryBytes = [0, 1, 2, 4][descriptor & 0x03]
    const contentSizeBytes = contentSizeFlag === 0 ? (singleSegment ? 1 : 0) : 2 ** contentSizeFlag
    let offset = 5 + windowBytes + dictionaryBytes + contentSizeBytes
    for (let last = false; !last; ) {
        if (offset + 3 > bytes.length) {
            return false
        }
        const header = bytes.readUIntLE(offset, 3)
        offset += 3
        last = (header & 1) === 1
        const blockType = (header >> 1) & 3
        if (blockType === 3) {
            return false
        }
        // An RLE block stores one byte however long its output is.
        offset += blockType === 1 ? 1 : header >>> 3
    }
    offset += (descriptor & 0x04) !== 0 ? 4 : 0
    return offset === bytes.length
}

async function decodeWithLimit(bytes: Buffer, encoding: string): Promise<Buffer> {
    const decoderFactory = decoderFactories[encoding]
    if (!decoderFactory) {
        throw new InvalidImageTransportError(
            'unsupported_content_encoding',
            `unsupported content-encoding: ${encoding}`
        )
    }
    if (encoding === 'zstd' && !isSingleCompleteZstdFrame(bytes)) {
        throw new InvalidImageTransportError('decompression_failed', 'invalid zstd content: not one complete frame')
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
        case 'image/svg+xml':
            return isSvgDocument(bytes)
    }
}

/** A prolog longer than this is not read, so a body of comments cannot make the check scan the whole image. */
const MAX_SVG_PROLOG_BYTES = 64 * 1024

/**
 * Whether the bytes are an XML document with an `svg` root. SVG has no signature, so the check skips what may come
 * before the root: a byte order mark, whitespace, the XML declaration and other processing instructions, comments and a
 * doctype. A doctype with an internal subset is refused, because its entities can change what the document holds.
 */
function isSvgDocument(bytes: Buffer): boolean {
    const text = bytes.toString('utf8', 0, Math.min(bytes.length, MAX_SVG_PROLOG_BYTES)).replace(/^\uFEFF/, '')
    let position = 0
    for (;;) {
        while (position < text.length && /\s/.test(text[position])) {
            position++
        }
        const skipped = [
            ['<?', '?>'],
            ['<!--', '-->'],
            ['<!DOCTYPE', '>'],
        ].find(([open]) => text.startsWith(open, position))
        if (!skipped) {
            break
        }
        const end = text.indexOf(skipped[1], position + skipped[0].length)
        if (end < 0 || (skipped[0] === '<!DOCTYPE' && text.slice(position, end).includes('['))) {
            return false
        }
        position = end + skipped[1].length
    }
    return /^<svg[\s/>]/.test(text.slice(position, position + 5))
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
