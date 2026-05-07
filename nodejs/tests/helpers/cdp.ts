import { mockProducer } from './mocks/producer.mock'

import { CdpConsumerBaseDeps } from '../../src/cdp/consumers/cdp-base.consumer'
import { CdpLegacyEventsConsumerDeps } from '../../src/cdp/consumers/cdp-legacy-event.consumer'
import {
    CdpProducerName,
    WAREHOUSE_PRODUCER,
    WARPSTREAM_CALCULATED_EVENTS_PRODUCER,
    WARPSTREAM_CYCLOTRON_PRODUCER,
    WARPSTREAM_INGESTION_PRODUCER,
} from '../../src/cdp/outputs/producers'
import { InternalCaptureService } from '../../src/common/services/internal-capture'
import { KafkaProducerRegistry } from '../../src/ingestion/outputs/kafka-producer-registry'
import { KafkaProducerWrapper } from '../../src/kafka/producer'
import { Hub } from '../../src/types'

/**
 * Single shared kafkaProducer is enough for tests — point every CDP producer
 * slot at it so the routing layer doesn't try to open a second connection.
 * Defaults to the in-memory mock for unit tests; e2e tests should pass a real
 * producer so messages actually flow through Kafka.
 */
function buildTestCdpProducerRegistry(
    kafkaProducer: KafkaProducerWrapper = mockProducer
): KafkaProducerRegistry<CdpProducerName> {
    return new KafkaProducerRegistry<CdpProducerName>({
        [WARPSTREAM_INGESTION_PRODUCER]: kafkaProducer,
        [WARPSTREAM_CALCULATED_EVENTS_PRODUCER]: kafkaProducer,
        [WARPSTREAM_CYCLOTRON_PRODUCER]: kafkaProducer,
        [WAREHOUSE_PRODUCER]: kafkaProducer,
    })
}

export function createCdpConsumerDeps(hub: Hub, kafkaProducer?: KafkaProducerWrapper): CdpConsumerBaseDeps {
    return {
        postgres: hub.postgres,
        pubSub: hub.pubSub,
        encryptedFields: hub.encryptedFields,
        teamManager: hub.teamManager,
        integrationManager: hub.integrationManager,
        cdpProducerRegistry: buildTestCdpProducerRegistry(kafkaProducer),
        internalCaptureService: new InternalCaptureService(hub),
        personRepository: hub.personRepository,
        geoipService: hub.geoipService,
        groupRepository: hub.groupRepository,
        quotaLimiting: hub.quotaLimiting,
    }
}

export function createCdpLegacyEventsConsumerDeps(
    hub: Hub,
    kafkaProducer?: KafkaProducerWrapper
): CdpLegacyEventsConsumerDeps {
    return {
        ...createCdpConsumerDeps(hub, kafkaProducer),
        groupTypeManager: hub.groupTypeManager,
    }
}
