import { getDefaultKafkaDownstreamProducerEnvConfig } from '@posthog/ingestion-common/outputs/producers'
import {
    getDefaultSessionRecordingApiConfig,
    getDefaultSessionRecordingConfig,
    getDefaultSessionReplayOutputsConfig,
} from '@posthog/replay-storage/config'
import { getDefaultKafkaSessionreplayProducerEnvConfig } from '@posthog/replay-storage/outputs/producer-config'

import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { getDefaultIngestionConsumerConfig } from '~/ingestion/config'
import { MlMirrorConfig, getMlMirrorConfig } from '~/ingestion/pipelines/sessionreplay/ml-mirror/config'

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
