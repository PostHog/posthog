import { BlockCompression } from '~/ingestion/pipelines/sessionreplay/sessions/block-compression'

/**
 * Measured 2026-09-19 on 1500 production blocks: quality 9 stores 0.53 of snappy for 25 times its CPU, and beats zstd
 * level 19 on both counts. Quality 5 stores 6% more for 46% of the CPU. Quality 11 stores 6% less, but costs 47 times
 * quality 9 and needs more packing throughput than the threadpool gives. This lane reads a block rarely and keeps it
 * for months, so it takes the bytes.
 */
export const ML_BLOCK_COMPRESSION = { codec: 'brotli', level: 9 } as const satisfies BlockCompression
