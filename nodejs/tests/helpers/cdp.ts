import { mockProducer } from '@posthog/node-common/testing/mocks/producer.mock'

import {
    CdpProducerName,
    WAREHOUSE_PRODUCER,
    WARPSTREAM_CYCLOTRON_PRODUCER,
    WARPSTREAM_INGESTION_PRODUCER,
} from '@posthog/hog-engine/cdp/outputs/producers'
import { GroupReadRepository } from '@posthog/ingestion-common/groups/repositories/group-repository.interface'
import { PersonReadRepository } from '@posthog/ingestion-common/persons/repositories/person-repository'
import { KafkaProducerWrapper } from '@posthog/node-common/kafka/producer'
import { KafkaProducerRegistry } from '@posthog/node-common/outputs/kafka-producer-registry'
import { InternalCaptureService } from '@posthog/node-common/services/internal-capture'

import { CdpConsumerBaseDeps } from '../../src/cdp/consumers/cdp-base.consumer'
import { createFrequencyCapValkeyPool } from '../../src/cdp/services/messaging/frequency-cap-valkey-pool'
import { createSesRateLimiterValkeyPool } from '../../src/cdp/services/rate-limiter/rate-limiter-valkey-pool'
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
        emailValidationValkey: createSesRateLimiterValkeyPool(hub, 'email-mx-validation'),
        frequencyCapValkey: createFrequencyCapValkeyPool(hub),
    }
}
