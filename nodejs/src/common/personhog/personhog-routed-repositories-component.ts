import { GroupRepository } from '~/common/groups/repositories/group-repository.interface'
import { PostgresGroupRepository } from '~/common/groups/repositories/postgres-group-repository'
import { PersonRepository } from '~/common/persons/repositories/person-repository'
import { PostgresPersonRepository } from '~/common/persons/repositories/postgres-person-repository'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { Component } from '~/ingestion/common/scopes'

import { PersonHogConfig, buildGroupRepository, buildPersonRepository, createPersonHogClient } from './index'

/** Extra config the routed repositories need beyond `PersonHogConfig`. */
export interface PersonHogRoutedRepositoriesConfig extends PersonHogConfig {
    PERSON_UPDATE_CALCULATE_PROPERTIES_SIZE: number
}

/** Person and group repositories, each routed to personhog or Postgres per rollout. */
export interface RoutedRepositories {
    personRepository: PersonRepository
    groupRepository: GroupRepository
}

/**
 * Scope owner for the person/group repositories used by write-capable ingestion
 * lanes (analytics). Unlike `PersonHogClientComponent`, the personhog client is
 * optional here: when personhog is unconfigured `createPersonHogClient` returns
 * `null` and both repositories fall back to Postgres. The nullable client is
 * owned entirely by this component — it never enters the scope container (which
 * only holds `object` values) — and is closed on `stop()`.
 */
export class PersonHogRoutedRepositoriesComponent implements Component<RoutedRepositories> {
    constructor(
        private readonly config: PersonHogRoutedRepositoriesConfig,
        private readonly postgres: PostgresRouter,
        private readonly clientLabel: string
    ) {}

    start(): Promise<{ value: RoutedRepositories; stop: () => Promise<void> }> {
        const client = createPersonHogClient(this.config)

        const postgresPersonRepository = new PostgresPersonRepository(this.postgres, {
            calculatePropertiesSize: this.config.PERSON_UPDATE_CALCULATE_PROPERTIES_SIZE,
        })
        const personRepository = buildPersonRepository(
            client,
            postgresPersonRepository,
            this.config.PERSONHOG_PERSONS_ROLLOUT_PERCENTAGE,
            this.config.PERSONHOG_PERSONS_ROLLOUT_TEAM_IDS,
            this.clientLabel
        )

        const postgresGroupRepository = new PostgresGroupRepository(this.postgres)
        const groupRepository = buildGroupRepository(
            client,
            postgresGroupRepository,
            this.config.PERSONHOG_GROUPS_ROLLOUT_PERCENTAGE,
            this.config.PERSONHOG_GROUPS_ROLLOUT_TEAM_IDS,
            this.clientLabel
        )

        return Promise.resolve({
            value: { personRepository, groupRepository },
            stop: () => {
                client?.close()
                return Promise.resolve()
            },
        })
    }
}
