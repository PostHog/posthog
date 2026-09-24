import {
    IngestionSessionReplayMlImageScrubServer,
    buildImageScrubConsumerConfig,
} from './ingestion-session-replay-ml-image-scrub-server'
import { buildMlMirrorServerConfig } from './ml-mirror-server-config'

class TestImageScrubServer extends IngestionSessionReplayMlImageScrubServer {
    public override startServices(): Promise<void> {
        return super.startServices()
    }
}

describe('image scrub server startup', () => {
    it.each(['', '   '])(
        'rejects key manager configuration without a DLQ before starting dependencies (%p)',
        async (topic) => {
            const server = new TestImageScrubServer({
                AI_RESEARCH_REPLAY_KEY_TABLE: 'key-table',
                AI_RESEARCH_REPLAY_KMS_KEY_ARN: '',
                SESSION_RECORDING_ML_IMAGE_SCRUB_DLQ_TOPIC: topic,
            })
            await expect(server.startServices()).rejects.toThrow('requires SESSION_RECORDING_ML_IMAGE_SCRUB_DLQ_TOPIC')
        }
    )

    it.each([
        // A batch is ceil(size / concurrency) waves of at most one scrub timeout, and every image must
        // be able to time out once inside the 240s of Kafka's 300s max.poll.interval.ms that scrub
        // timeouts may use.
        { batchSize: 150, concurrency: 14, timeoutMs: 45_000, expected: 70 },
        { batchSize: 150, concurrency: 8, timeoutMs: 45_000, expected: 40 },
        { batchSize: 50, concurrency: 14, timeoutMs: 45_000, expected: 50 },
        { batchSize: 150, concurrency: 14, timeoutMs: 15_000, expected: 150 },
    ])(
        'polls at most the messages that can each time out once inside the poll interval (%p)',
        ({ batchSize, concurrency, timeoutMs, expected }) => {
            const config = buildMlMirrorServerConfig({
                SESSION_RECORDING_ML_IMAGE_SCRUB_BATCH_SIZE: batchSize,
                SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_CONCURRENCY: concurrency,
                SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_TIMEOUT_MS: timeoutMs,
            })
            expect(buildImageScrubConsumerConfig(config).fetchBatchSize).toBe(expected)
        }
    )

    it('allows a disabled DLQ without a key manager and continues to the S3 configuration check', async () => {
        const server = new TestImageScrubServer({
            AI_RESEARCH_REPLAY_KEY_TABLE: '',
            SESSION_RECORDING_ML_IMAGE_SCRUB_DLQ_TOPIC: '',
            SESSION_RECORDING_V2_S3_BUCKET: '',
        })
        await expect(server.startServices()).rejects.toThrow('SESSION_RECORDING_V2_S3_*')
    })
})
