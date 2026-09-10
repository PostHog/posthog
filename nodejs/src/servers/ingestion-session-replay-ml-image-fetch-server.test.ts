import {
    buildImageFetchConsumerConfigs,
    buildImageFetchConsumerOverrides,
} from './ingestion-session-replay-ml-image-fetch-server'
import { buildMlMirrorServerConfig } from './ingestion-session-replay-ml-mirror-server'

describe('image fetch consumer wiring', () => {
    it.each([
        ['the default', {}, 2, 102_400],
        ['four consumers', { SESSION_RECORDING_ML_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH: 4 }, 4, 102_400],
        ['eight consumers', { SESSION_RECORDING_ML_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH: 8 }, 8, 204_800],
        ['sixteen consumers', { SESSION_RECORDING_ML_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH: 16 }, 16, 409_600],
    ])('creates %s number of Kafka group members', (_name, overrides, expectedConsumers, expectedQueueBudget) => {
        const serverConfig = buildMlMirrorServerConfig(overrides)
        const consumerConfigs = buildImageFetchConsumerConfigs(serverConfig)
        const consumerOverrides = buildImageFetchConsumerOverrides(serverConfig, consumerConfigs.length)

        expect(consumerConfigs).toHaveLength(expectedConsumers)
        expect(consumerConfigs.map((config) => config.groupId)).toEqual(
            Array(expectedConsumers).fill(serverConfig.SESSION_RECORDING_ML_IMAGE_FETCH_GROUP_ID)
        )
        expect(Number(consumerOverrides['queued.max.messages.kbytes']) * expectedConsumers).toBeLessThanOrEqual(
            expectedQueueBudget
        )
        expect(Number(consumerOverrides['queued.max.messages.kbytes']) * expectedConsumers).toBeGreaterThanOrEqual(
            expectedQueueBudget - expectedConsumers
        )
        expect(Number(consumerOverrides['queued.max.messages.kbytes']) * 1024).toBeGreaterThanOrEqual(
            serverConfig.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES + 64 * 1024
        )
    })

    it.each([0, -1, 1.5, 17, Number.NaN, Number.MAX_SAFE_INTEGER + 1])(
        'refuses invalid target partition count %p',
        (targetPartitionsPerBatch) => {
            const serverConfig = buildMlMirrorServerConfig({
                SESSION_RECORDING_ML_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH: targetPartitionsPerBatch,
            })

            expect(() => buildImageFetchConsumerConfigs(serverConfig)).toThrow(
                'image fetch batch target must be an integer between 1 and 16'
            )
        }
    )
})
