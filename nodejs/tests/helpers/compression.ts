import { BrotliCompress, Deflate, Gzip, constants, createBrotliCompress, createDeflate, createGzip } from 'zlib'

export type ContentEncoding = 'gzip' | 'deflate' | 'br'

const encoders: Record<ContentEncoding, () => Gzip | Deflate | BrotliCompress> = {
    gzip: () => createGzip(),
    deflate: () => createDeflate(),
    br: () => createBrotliCompress({ params: { [constants.BROTLI_PARAM_QUALITY]: 1 } }),
}

export const compressWithoutEnding = async (
    encoding: ContentEncoding,
    chunk: Buffer,
    times: number
): Promise<Buffer> => {
    const encoder = encoders[encoding]()
    const parts: Buffer[] = []
    encoder.on('data', (part: Buffer) => parts.push(part))
    for (let written = 0; written < times; written++) {
        encoder.write(chunk)
    }
    await new Promise<void>((resolve) => encoder.flush(() => resolve()))
    encoder.destroy()
    return Buffer.concat(parts)
}

const flushedOutput = async (encoder: Gzip | Deflate, decodedBytes: number): Promise<Buffer> => {
    const parts: Buffer[] = []
    const collect = (part: Buffer): number => parts.push(part)
    encoder.on('data', collect)
    encoder.write(Buffer.alloc(decodedBytes, ' '))
    await new Promise<void>((resolve) => encoder.flush(() => resolve()))
    encoder.off('data', collect)
    return Buffer.concat(parts)
}

const emptyStoredBlock = Buffer.from([0x00, 0x00, 0x00, 0xff, 0xff])

export const compressTwoPartsApart = async (
    encoding: 'gzip' | 'deflate',
    decodedBytesPerPart: number,
    gapBytes: number
): Promise<Buffer> => {
    const encoder = encoding === 'gzip' ? createGzip() : createDeflate()
    const first = await flushedOutput(encoder, decodedBytesPerPart)
    const gap = Buffer.concat(Array(Math.ceil(gapBytes / emptyStoredBlock.length)).fill(emptyStoredBlock))
    const second = await flushedOutput(encoder, decodedBytesPerPart)
    encoder.destroy()
    return Buffer.concat([first, gap, second])
}
