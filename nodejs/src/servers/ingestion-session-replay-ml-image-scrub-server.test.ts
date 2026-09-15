import { IngestionSessionReplayMlImageScrubServer } from './ingestion-session-replay-ml-image-scrub-server'

class TestImageScrubServer extends IngestionSessionReplayMlImageScrubServer {
    public override startServices(): Promise<void> {
        return super.startServices()
    }
}

describe('image scrub server startup', () => {
    it.each(['', '   '])(
        'rejects privacy configuration without a DLQ before starting dependencies (%p)',
        async (topic) => {
            const server = new TestImageScrubServer({
                AI_RESEARCH_REPLAY_KEY_TABLE: 'privacy-table',
                AI_RESEARCH_REPLAY_KMS_KEY_ARN: '',
                SESSION_RECORDING_ML_IMAGE_SCRUB_DLQ_TOPIC: topic,
            })
            await expect(server.startServices()).rejects.toThrow('requires SESSION_RECORDING_ML_IMAGE_SCRUB_DLQ_TOPIC')
        }
    )

    it('allows a disabled DLQ without privacy and continues to the S3 configuration check', async () => {
        const server = new TestImageScrubServer({
            AI_RESEARCH_REPLAY_KEY_TABLE: '',
            SESSION_RECORDING_ML_IMAGE_SCRUB_DLQ_TOPIC: '',
            SESSION_RECORDING_V2_S3_BUCKET: '',
        })
        await expect(server.startServices()).rejects.toThrow('SESSION_RECORDING_V2_S3_*')
    })
})
