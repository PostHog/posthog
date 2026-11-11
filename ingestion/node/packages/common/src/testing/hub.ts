import { PluginsServerConfig } from '@posthog/node-common/types'
import { createHub as createCommonHub } from '@posthog/node-common/utils/db/hub'

import { GroupTypeManager } from '~/groups/group-type-manager'
import { PostgresGroupRepository } from '~/groups/repositories/postgres-group-repository'
import { buildGroupRepository, buildPersonRepository, createPersonHogClient } from '~/personhog'
import { PostgresPersonRepository } from '~/persons/repositories/postgres-person-repository'
import { Hub } from '~/types'

export { closeHub, createEventsToDropByToken } from '@posthog/node-common/utils/db/hub'

/** The common test hub plus the person, group and personhog services ingestion's code expects on it. */
export async function createHub(config: Partial<PluginsServerConfig> = {}): Promise<Hub> {
    const hub = await createCommonHub(config)
    const personhogClient = createPersonHogClient(hub)
    const clientLabel = hub.PLUGIN_SERVER_MODE ?? 'unknown'
    const postgresGroupRepository = new PostgresGroupRepository(hub.postgres)
    const postgresPersonRepository = new PostgresPersonRepository(hub.postgres, {
        // createHub is test-only; ingestion configures this on its own infra (see createIngestionTestInfra).
        calculatePropertiesSize: 0,
    })
    const personRepository = buildPersonRepository(
        personhogClient,
        postgresPersonRepository,
        hub.PERSONHOG_PERSONS_ROLLOUT_PERCENTAGE,
        hub.PERSONHOG_PERSONS_ROLLOUT_TEAM_IDS,
        clientLabel
    )
    const groupRepository = buildGroupRepository(
        personhogClient,
        postgresGroupRepository,
        hub.PERSONHOG_GROUPS_ROLLOUT_PERCENTAGE,
        hub.PERSONHOG_GROUPS_ROLLOUT_TEAM_IDS,
        clientLabel
    )
    const groupTypeManager = new GroupTypeManager(groupRepository, hub.teamManager)
    return { ...hub, personRepository, groupRepository, groupTypeManager }
}
