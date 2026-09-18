import { BlockCompression } from '~/ingestion/pipelines/sessionreplay/sessions/block-compression'

/**
 * Measured 2026-09-18 on rrweb-shaped session blocks: quality 9 stores about 20x against snappy's 6x for roughly 16x
 * its CPU, and beats zstd level 19 on both counts. Quality 5 stores about 7% more for half the CPU, and quality 11
 * costs about 77 times quality 9 for a tenth more saving. This lane reads a block rarely and keeps it for months, so
 * it takes the bytes.
 */
export const ML_BLOCK_COMPRESSION = { codec: 'brotli', level: 9 } as const satisfies BlockCompression
