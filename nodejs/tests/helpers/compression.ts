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
