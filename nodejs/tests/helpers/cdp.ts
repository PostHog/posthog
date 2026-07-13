import { mockProducer } from './mocks/producer.mock'

import { GroupReadRepository } from '~/common/groups/repositories/group-repository.interface'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PersonReadRepository } from '~/common/persons/repositories/person-repository'

import { CdpConsumerBaseDeps } from '../../src/cdp/consumers/cdp-base.consumer'
import {
    CdpProducerName,
    WAREHOUSE_PRODUCER,
    WARPSTREAM_CALCULATED_EVENTS_PRODUCER,
    WARPSTREAM_CYCLOTRON_PRODUCER,
    WARPSTREAM_INGESTION_PRODUCER,
} from '../../src/cdp/outputs/producers'
import { InternalCaptureService } from '../../src/common/services/internal-capture'
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

/**
 * No-op read repositories for tests that don't exercise person/group lookups.
 * Tests that need real resolution should override via spread.
 */
const noopGroupReadRepository: GroupReadRepository = {
    fetchGroupsByKeys: () => Promise.resolve([]),
    fetchGroupTypesByTeamIds: () => Promise.resolve({}),
    fetchGroupTypesByProjectIds: () => Promise.resolve({}),
}

const noopPersonReadRepository: PersonReadRepository = {
    fetchPerson: () => Promise.resolve(undefined),
    fetchPersonsByDistinctIds: () => Promise.resolve([]),
    fetchPersonsByPersonIds: () => Promise.resolve([]),
    fetchDistinctIdsForPersons: () => Promise.resolve({}),
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
        personRepository: noopPersonReadRepository,
        geoipService: hub.geoipService,
        groupRepository: noopGroupReadRepository,
        quotaLimiting: hub.quotaLimiting,
    }
}
