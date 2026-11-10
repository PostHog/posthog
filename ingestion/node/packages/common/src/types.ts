import { Hub as CommonHub, HubServices as CommonHubServices } from '@posthog/node-common/types'

import { GroupTypeManager } from '~/groups/group-type-manager'
import { GroupRepository } from '~/groups/repositories/group-repository.interface'
import { PersonRepository } from '~/persons/repositories/person-repository'

/** The person and group services a host adds to the common hub when it runs ingestion's code. */
export interface PersonServices {
    groupTypeManager: GroupTypeManager
    groupRepository: GroupRepository
    personRepository: PersonRepository
}

export interface HubServices extends CommonHubServices, PersonServices {}

export interface Hub extends CommonHub, PersonServices {}
