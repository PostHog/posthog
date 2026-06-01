import {
    INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP,
    INGESTION_PRODUCER_CONFIG_MAP,
    WARPSTREAM_PRODUCER_CONFIG_MAP,
} from '../../ingestion/common/config'
import {
    DEFAULT_PRODUCER,
    INGESTION_DOWNSTREAM_PRODUCER,
    INGESTION_PRODUCER,
    WARPSTREAM_PRODUCER,
} from '../../ingestion/common/outputs'
import { KafkaProducerRegistryBuilder } from '../../ingestion/outputs/kafka-producer-registry-builder'
import {
    INGESTION_SESSIONREPLAY_PRODUCER,
    INGESTION_SESSIONREPLAY_PRODUCER_CONFIG_MAP,
    SESSION_REPLAY_DEFAULT_PRODUCER_CONFIG_MAP,
} from '../../session-replay/shared/outputs/producer-config'

/**
 * Session replay's producer slots. Legacy DEFAULT/WARPSTREAM/INGESTION plus the consolidated
 * slots it is migrating to: DOWNSTREAM (warpstream-ingestion, from ingestion common) and
 * SESSIONREPLAY (warpstream-replay, defined in the session-replay folder). It does not use
 * UPSTREAM — replay's re-consumed topics live on the replay cluster (SESSIONREPLAY), not MSK.
 */
export function createProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(DEFAULT_PRODUCER, SESSION_REPLAY_DEFAULT_PRODUCER_CONFIG_MAP)
        .register(WARPSTREAM_PRODUCER, WARPSTREAM_PRODUCER_CONFIG_MAP)
        .register(INGESTION_PRODUCER, INGESTION_PRODUCER_CONFIG_MAP)
        .register(INGESTION_DOWNSTREAM_PRODUCER, INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP)
        .register(INGESTION_SESSIONREPLAY_PRODUCER, INGESTION_SESSIONREPLAY_PRODUCER_CONFIG_MAP)
}
