import { Transform } from 'stream'
import { finished } from 'stream/promises'
import { constants, createBrotliCompress, createDeflate, createGzip } from 'zlib'

export type ContentEncoding = 'gzip' | 'deflate' | 'br'

const encoders: Record<ContentEncoding, () => Transform> = {
    gzip: () => createGzip(),
    deflate: () => createDeflate(),
    br: () => createBrotliCompress({ params: { [constants.BROTLI_PARAM_QUALITY]: 1 } }),
}

export const compressRepeated = async (encoding: ContentEncoding, chunk: Buffer, times: number): Promise<Buffer> => {
    const encoder = encoders[encoding]()
    const parts: Buffer[] = []
    encoder.on('data', (part: Buffer) => parts.push(part))
    for (let written = 0; written < times; written++) {
        encoder.write(chunk)
    }
    encoder.end()
    await finished(encoder)
    return Buffer.concat(parts)
}
