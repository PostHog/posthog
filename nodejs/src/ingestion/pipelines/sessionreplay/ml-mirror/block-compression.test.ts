import { brotliCompressSync, constants } from 'node:zlib'

import { logger } from '~/common/utils/logger'
import { compressBlock } from '~/ingestion/pipelines/sessionreplay/sessions/block-compression'

import { ML_BLOCK_COMPRESSION } from './block-compression'

let addonLoaded = false
try {
    require('@posthog/replay-anonymizer')
    addonLoaded = true
} catch (e) {
    if (process.env.CI) {
        throw new Error(`replay-anonymizer addon failed to load; the ML block compression test cannot run in CI: ${e}`)
    }
    logger.warn('🙈', 'replay_anonymizer_addon_not_built_skipping_ml_block_compression_test')
}

const describeAddon = addonLoaded ? describe : describe.skip
describeAddon('ML block compression', () => {
    it('writes the same bytes as zlib at the same quality', async () => {
        const block = Buffer.from(
            Array.from({ length: 3000 }, (_, i) =>
                JSON.stringify({
                    type: 3,
                    timestamp: 1_700_000_000_000 + i * 16,
                    data: { source: 1, positions: [{ x: (i * 37) % 1280, y: (i * 91) % 720, id: i % 53 }] },
                })
            ).join('\n')
        )

        const zlibBytes = brotliCompressSync(block, {
            params: {
                [constants.BROTLI_PARAM_QUALITY]: ML_BLOCK_COMPRESSION.level,
                [constants.BROTLI_PARAM_SIZE_HINT]: block.length,
            },
        })
        expect(Buffer.compare(await compressBlock(block, ML_BLOCK_COMPRESSION), zlibBytes)).toBe(0)
    })
})
