import { S3Client } from '@aws-sdk/client-s3'

import { buildMlMirrorServerConfig } from './ingestion-session-replay-ml-mirror-server'
import { buildSinkConsumerConfig, requireS3Client } from './ingestion-session-replay-ml-parquet-sink-server'

describe('Parquet sink wiring', () => {
    describe('buildSinkConsumerConfig', () => {
        it('uses manual offsets so a flush commits only after the S3 write (at-least-once)', () => {
            const config = buildSinkConsumerConfig(buildMlMirrorServerConfig({}))
            expect(config.autoOffsetStore).toBe(false)
            expect(config.autoCommit).toBe(true)
            expect(config.callEachBatchWhenEmpty).toBe(true)
        })

        it('consumes the ML metadata topic under the sink group id', () => {
            const merged = buildMlMirrorServerConfig({})
            const config = buildSinkConsumerConfig(merged)
            expect(config.topic).toBe(merged.INGESTION_SESSIONREPLAY_OUTPUT_ML_BLOCK_METADATA_TOPIC)
            expect(config.groupId).toBe(merged.SESSION_RECORDING_ML_PARQUET_SINK_GROUP_ID)
        })
    })

    describe('requireS3Client', () => {
        it('throws when S3 is not configured (the sink writes unencrypted, must not silently no-op)', () => {
            expect(() => requireS3Client(null)).toThrow('SESSION_RECORDING_V2_S3_')
        })

        it('passes a configured client through', () => {
            const client = {} as S3Client
            expect(requireS3Client(client)).toBe(client)
        })
    })
})
