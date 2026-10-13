import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { getDefaultKafkaDownstreamProducerEnvConfig } from '~/ingestion/common/outputs/producers'
import { getDefaultIngestionConsumerConfig } from '~/ingestion/config'
import {
    getDefaultSessionRecordingApiConfig,
    getDefaultSessionRecordingConfig,
    getDefaultSessionReplayOutputsConfig,
} from '~/ingestion/pipelines/sessionreplay/config'
import { MlMirrorConfig, getMlMirrorConfig } from '~/ingestion/pipelines/sessionreplay/ml-mirror/config'
import { getDefaultKafkaSessionreplayProducerEnvConfig } from '~/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'

import type { IngestionSessionReplayServerConfig } from './ingestion-session-replay-server'

/** Full config for an ML mirror deployment: the primary replay config plus ML knobs. */
export type IngestionSessionReplayMlMirrorServerConfig = IngestionSessionReplayServerConfig & MlMirrorConfig

/** Assembles the ML-mirror config; shared by the mirror ingester and the Parquet-sink deployments. */
export function buildMlMirrorServerConfig(
    config: Partial<IngestionSessionReplayMlMirrorServerConfig>
): IngestionSessionReplayMlMirrorServerConfig {
    return {
        ...defaultConfig,
        ...overrideConfigWithEnv(getDefaultIngestionConsumerConfig()),
        ...overrideConfigWithEnv(getDefaultKafkaDownstreamProducerEnvConfig()),
        ...overrideConfigWithEnv(getDefaultKafkaSessionreplayProducerEnvConfig()),
        ...overrideConfigWithEnv({
            ...getDefaultSessionRecordingConfig(),
            // Distinct default group id so the mirror gets its own copy of every recording rather than
            // splitting the snapshot topic's partitions with the primary ingester (still env-overridable).
            INGESTION_SESSION_REPLAY_CONSUMER_GROUP_ID: 'session-replay-ml-mirror',
        }),
        ...overrideConfigWithEnv(getDefaultSessionRecordingApiConfig()),
        ...overrideConfigWithEnv(getDefaultSessionReplayOutputsConfig()),
        ...getMlMirrorConfig(),
        ...config,
    }
}
