import { KAFKA_SESSION_REPLAY_ML_BLOCK_METADATA } from '~/common/config/kafka-topics'
import { getDefaultSessionRecordingConfig } from '~/ingestion/pipelines/sessionreplay/config'

import {
    IngestionSessionReplayMlMirrorServer,
    buildMlMirrorServerConfig,
} from './ingestion-session-replay-ml-mirror-server'

describe('buildMlMirrorServerConfig', () => {
    it.each(['S3_PREFIX', 'PSEUDONYM_SECRET', 'PSEUDONYM_KMS_REGION', 'PSEUDONYM_KEY_FINGERPRINT'] as const)(
        'applies the legacy %s environment alias when building server configuration',
        (suffix) => {
            const legacy = `SESSION_RECORDING_ML_${suffix}`
            const canonical = `AI_RESEARCH_REPLAY_${suffix}` as const
            const originalEnv = process.env
            try {
                process.env = { ...originalEnv, [legacy]: 'legacy-value' }
                delete process.env[canonical]
                expect(buildMlMirrorServerConfig({})[canonical]).toBe('legacy-value')
                process.env[canonical] = 'canonical-value'
                expect(buildMlMirrorServerConfig({})[canonical]).toBe('canonical-value')
            } finally {
                process.env = originalEnv
            }
        }
    )
    it.each([
        ['', ''],
        ['key-table', ''],
        ['', 'kms-key'],
    ])('rejects missing key manager configuration before starting services (%s, %s)', (table, kmsKey) => {
        expect(
            () =>
                new IngestionSessionReplayMlMirrorServer({
                    AI_RESEARCH_REPLAY_KEY_TABLE: table,
                    AI_RESEARCH_REPLAY_KMS_KEY_ARN: kmsKey,
                })
        ).toThrow('ML key manager requires a DynamoDB table and a KMS key ARN')
    })

    it('defaults the mirror to its own consumer group, distinct from the primary ingester', () => {
        const config = buildMlMirrorServerConfig({})
        expect(config.INGESTION_SESSION_REPLAY_CONSUMER_GROUP_ID).toBe('session-replay-ml-mirror')
        // Regression guard for the group-id collision: must not inherit the primary default.
        expect(config.INGESTION_SESSION_REPLAY_CONSUMER_GROUP_ID).not.toBe(
            getDefaultSessionRecordingConfig().INGESTION_SESSION_REPLAY_CONSUMER_GROUP_ID
        )
    })

    it('wires the ML metadata topic and a flush interval safely under max.poll.interval.ms', () => {
        const config = buildMlMirrorServerConfig({})
        expect(config.INGESTION_SESSIONREPLAY_OUTPUT_ML_BLOCK_METADATA_TOPIC).toBe(
            KAFKA_SESSION_REPLAY_ML_BLOCK_METADATA
        )
        expect(config.SESSION_RECORDING_ML_METADATA_PREFIX).toBe('block-metadata')
        expect(config.AI_RESEARCH_REPLAY_S3_PREFIX).toBe('rrweb_2')
        expect(config.SESSION_RECORDING_ML_PARQUET_FLUSH_INTERVAL_MS).toBeLessThan(300_000)
    })

    it('lets an explicit override win over the mirror default', () => {
        const config = buildMlMirrorServerConfig({
            INGESTION_SESSION_REPLAY_CONSUMER_GROUP_ID: 'custom-group',
            SESSION_RECORDING_V2_S3_PREFIX: 'rrweb',
        })
        expect(config.INGESTION_SESSION_REPLAY_CONSUMER_GROUP_ID).toBe('custom-group')
        expect(config.AI_RESEARCH_REPLAY_S3_PREFIX).toBe('rrweb_2')
    })
})
