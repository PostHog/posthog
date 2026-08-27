import { buildImageFetchConsumerConfig } from './ingestion-session-replay-ml-image-fetch-server'
import { buildMlMirrorServerConfig } from './ingestion-session-replay-ml-mirror-server'

describe('image fetch consumer wiring', () => {
    it.each([
        ['the default', {}, 2],
        ['an explicit override', { SESSION_RECORDING_ML_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH: 4 }, 4],
    ])('uses %s to combine batches from configured partitions', (_name, overrides, expectedPartitions) => {
        const serverConfig = buildMlMirrorServerConfig(overrides)

        expect(buildImageFetchConsumerConfig(serverConfig).targetPartitionsPerBatch).toBe(expectedPartitions)
    })
})
