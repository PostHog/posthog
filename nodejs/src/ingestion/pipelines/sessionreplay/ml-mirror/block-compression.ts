import { BlockCompression } from '~/ingestion/pipelines/sessionreplay/sessions/block-compression'

import { getRustAnonymizer } from './rust-anonymizer'

/**
 * Measured 2026-09-19 on 1500 production blocks: quality 9 stores 0.53 of snappy for 25 times its CPU, and beats zstd
 * level 19 on both counts. Quality 5 stores 6% more for 46% of the CPU. Quality 11 stores 6% less, but costs 47 times
 * quality 9 and needs more packing throughput than the threadpool gives. This lane reads a block rarely and keeps it
 * for months, so it takes the bytes.
 *
 * The addon runs the same C encoder as zlib and writes the same bytes. zlib reports the encoder's working memory at
 * quality 9 to V8 as external memory, which caused most of this lane's full GCs in October 2026.
 */
export const ML_BLOCK_COMPRESSION = {
    codec: 'brotli',
    level: 9,
    encoder: (data, quality) => getRustAnonymizer().compressBrotli(data, quality),
} as const satisfies BlockCompression
