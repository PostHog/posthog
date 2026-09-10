import { KAFKA_SESSION_REPLAY_ML_BLOCK_METADATA } from '~/common/config/kafka-topics'
import { getDefaultSessionRecordingConfig } from '~/ingestion/pipelines/sessionreplay/config'

import { buildMlMirrorServerConfig } from './ingestion-session-replay-ml-mirror-server'

describe('buildMlMirrorServerConfig', () => {
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
        expect(config.SESSION_RECORDING_ML_PARQUET_FLUSH_INTERVAL_MS).toBeLessThan(300_000)
    })

    it('lets an explicit override win over the mirror default', () => {
        const config = buildMlMirrorServerConfig({ INGESTION_SESSION_REPLAY_CONSUMER_GROUP_ID: 'custom-group' })
        expect(config.INGESTION_SESSION_REPLAY_CONSUMER_GROUP_ID).toBe('custom-group')
    })
})
