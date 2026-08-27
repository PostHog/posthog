import { buildImageFetchConsumerConfigs } from './ingestion-session-replay-ml-image-fetch-server'
import { buildMlMirrorServerConfig } from './ingestion-session-replay-ml-mirror-server'

describe('image fetch consumer wiring', () => {
    it.each([
        ['the default', {}, 2],
        ['an explicit override', { SESSION_RECORDING_ML_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH: 4 }, 4],
    ])('creates %s number of Kafka group members', (_name, overrides, expectedConsumers) => {
        const serverConfig = buildMlMirrorServerConfig(overrides)
        const consumerConfigs = buildImageFetchConsumerConfigs(serverConfig)

        expect(consumerConfigs).toHaveLength(expectedConsumers)
        expect(consumerConfigs.map((config) => config.groupId)).toEqual(
            Array(expectedConsumers).fill(serverConfig.SESSION_RECORDING_ML_IMAGE_FETCH_GROUP_ID)
        )
    })

    it.each([0, -1, 1.5, 5, Number.NaN, Number.MAX_SAFE_INTEGER + 1])(
        'refuses invalid target partition count %p',
        (targetPartitionsPerBatch) => {
            const serverConfig = buildMlMirrorServerConfig({
                SESSION_RECORDING_ML_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH: targetPartitionsPerBatch,
            })

            expect(() => buildImageFetchConsumerConfigs(serverConfig)).toThrow(
                'image fetch batch target must be an integer between 1 and 4'
            )
        }
    )
})
