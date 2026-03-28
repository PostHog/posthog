import { CdpConsumerBaseDeps } from '../../src/cdp/consumers/cdp-base.consumer'
import { CdpLegacyEventsConsumerDeps } from '../../src/cdp/consumers/cdp-legacy-event.consumer'
import { Hub } from '../../src/types'

export function createCdpConsumerDeps(hub: Hub): CdpConsumerBaseDeps {
    return {
        postgres: hub.postgres,
        pubSub: hub.pubSub,
        encryptedFields: hub.encryptedFields,
        teamManager: hub.teamManager,
        integrationManager: hub.integrationManager,
        kafkaProducer: hub.kafkaProducer,
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
