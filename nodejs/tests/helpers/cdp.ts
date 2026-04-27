import { CdpConsumerBaseDeps } from '../../src/cdp/consumers/cdp-base.consumer'
import { CdpLegacyEventsConsumerDeps } from '../../src/cdp/consumers/cdp-legacy-event.consumer'
import {
    CdpProducerName,
    MSK_PRODUCER,
    WAREHOUSE_PRODUCER,
    WARPSTREAM_CALCULATED_EVENTS_PRODUCER,
    WARPSTREAM_CYCLOTRON_PRODUCER,
    WARPSTREAM_INGESTION_PRODUCER,
} from '../../src/cdp/outputs/producers'
import { InternalCaptureService } from '../../src/common/services/internal-capture'
import { KafkaProducerRegistry } from '../../src/ingestion/outputs/kafka-producer-registry'
import { Hub } from '../../src/types'

/**
 * Single shared kafkaProducer is enough for tests — point every CDP producer
 * slot at it so the routing layer doesn't try to open a second connection.
 */
function buildTestCdpProducerRegistry(hub: Hub): KafkaProducerRegistry<CdpProducerName> {
    return new KafkaProducerRegistry<CdpProducerName>({
        [WARPSTREAM_INGESTION_PRODUCER]: hub.kafkaProducer,
        [WARPSTREAM_CALCULATED_EVENTS_PRODUCER]: hub.kafkaProducer,
        [WARPSTREAM_CYCLOTRON_PRODUCER]: hub.kafkaProducer,
        [MSK_PRODUCER]: hub.kafkaProducer,
        [WAREHOUSE_PRODUCER]: hub.kafkaProducer,
    })
}

export function createCdpConsumerDeps(hub: Hub): CdpConsumerBaseDeps {
    return {
        postgres: hub.postgres,
        pubSub: hub.pubSub,
        encryptedFields: hub.encryptedFields,
        teamManager: hub.teamManager,
        integrationManager: hub.integrationManager,
        cdpProducerRegistry: buildTestCdpProducerRegistry(hub),
        internalCaptureService: new InternalCaptureService(hub),
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
