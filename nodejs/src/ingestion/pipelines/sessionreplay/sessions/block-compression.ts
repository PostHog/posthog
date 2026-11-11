import { brotliCompress, constants } from 'node:zlib'
import snappy from 'snappy'

export type BrotliEncoder = (data: Buffer, quality: number) => Promise<Buffer>

/** A brotli `encoder` replaces Node's zlib and must write a stream that zlib can decompress. */
export type BlockCompression = { codec: 'brotli'; level: number; encoder?: BrotliEncoder } | { codec: 'snappy' }

export const DEFAULT_BLOCK_COMPRESSION: BlockCompression = { codec: 'snappy' }

/** Both codecs pack on the libuv threadpool, not on the event loop. */
export async function compressBlock(data: Buffer, compression: BlockCompression): Promise<Buffer> {
    switch (compression.codec) {
        case 'snappy':
            return snappy.compress(data)
        case 'brotli':
            if (compression.encoder) {
                return compression.encoder(data, compression.level)
            }
            return new Promise((resolve, reject) => {
                // We tried setting LGWIN:24, but this performed worse than leaving it unset. Just leave this unset
                // and let Brotli choose a good enough value.
                brotliCompress(
                    data,
                    {
                        params: {
                            [constants.BROTLI_PARAM_QUALITY]: compression.level,
                            [constants.BROTLI_PARAM_SIZE_HINT]: data.length,
                        },
                    },
                    (error, result) => (error ? reject(error) : resolve(result))
                )
            })
        default: {
            const _exhaustive: never = compression
            throw new Error(`Unknown block codec: ${JSON.stringify(_exhaustive)}`)
        }
    }
}
