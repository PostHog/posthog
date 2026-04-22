import { CdpConsumerBaseDeps } from '../../src/cdp/consumers/cdp-base.consumer'
import { CdpLegacyEventsConsumerDeps } from '../../src/cdp/consumers/cdp-legacy-event.consumer'
import { CdpProducerName, MSK_PRODUCER, WARPSTREAM_INGESTION_PRODUCER } from '../../src/cdp/outputs/producers'
import { KafkaProducerRegistry } from '../../src/ingestion/outputs/kafka-producer-registry'
import { Hub } from '../../src/types'

/**
 * Single shared kafkaProducer is enough for tests — point every CDP producer
 * slot at it so the routing layer doesn't try to open a second connection.
 */
function buildTestCdpProducerRegistry(hub: Hub): KafkaProducerRegistry<CdpProducerName> {
    return new KafkaProducerRegistry<CdpProducerName>({
        [WARPSTREAM_INGESTION_PRODUCER]: hub.kafkaProducer,
        [MSK_PRODUCER]: hub.kafkaProducer,
    })
}

export function createCdpConsumerDeps(hub: Hub): CdpConsumerBaseDeps {
    return {
        postgres: hub.postgres,
        pubSub: hub.pubSub,
        encryptedFields: hub.encryptedFields,
        teamManager: hub.teamManager,
        integrationManager: hub.integrationManager,
        kafkaProducer: hub.kafkaProducer,
        cdpProducerRegistry: buildTestCdpProducerRegistry(hub),
        internalCaptureService: hub.internalCaptureService,
        personRepository: hub.personRepository,
        geoipService: hub.geoipService,
        groupRepository: hub.groupRepository,
        quotaLimiting: hub.quotaLimiting,
    }
}

export function createCdpLegacyEventsConsumerDeps(hub: Hub): CdpLegacyEventsConsumerDeps {
    return {
        ...createCdpConsumerDeps(hub),
        groupTypeManager: hub.groupTypeManager,
    }
}
