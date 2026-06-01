import { INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP } from '../../ingestion/common/config'
import { INGESTION_DOWNSTREAM_PRODUCER } from '../../ingestion/common/outputs'
import { KafkaProducerRegistryBuilder } from '../../ingestion/outputs/kafka-producer-registry-builder'
import {
    INGESTION_SESSIONREPLAY_PRODUCER,
    INGESTION_SESSIONREPLAY_PRODUCER_CONFIG_MAP,
} from '../../session-replay/shared/outputs/producer-config'

/**
 * Session replay's producer slots: DOWNSTREAM (warpstream-ingestion, from ingestion common)
 * for ClickHouse-bound outputs, and SESSIONREPLAY (warpstream-replay) for replay-domain topics
 * including their DLQ and overflow. The legacy DEFAULT/WARPSTREAM/INGESTION slots have been
 * retired here; replay does not use UPSTREAM.
 */
export function createProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(INGESTION_DOWNSTREAM_PRODUCER, INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP)
        .register(INGESTION_SESSIONREPLAY_PRODUCER, INGESTION_SESSIONREPLAY_PRODUCER_CONFIG_MAP)
}
