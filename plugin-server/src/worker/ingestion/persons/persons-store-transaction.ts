import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../types'
import { MoveDistinctIdsResult } from '../../../utils/db/db'

export interface PersonsStoreTransaction {
    /**
     * Creates a new person
     */
    createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        distinctIds?: { distinctId: string; version?: number }[]
    ): Promise<[InternalPerson, TopicMessage[]]>

    /**
     * Updates an existing person for merge operations
     */
    updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string
    ): Promise<[InternalPerson, TopicMessage[], boolean]>

    /**
     * Updates person for regular updates with specific properties to set and unset
     */
    updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string
    ): Promise<[InternalPerson, TopicMessage[], boolean]>

    /**
     * Deletes a person
     */
    deletePerson(person: InternalPerson, distinctId: string): Promise<TopicMessage[]>

    /**
     * Adds a distinct ID to a person
     */
    addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<TopicMessage[]>

    /**
     * Moves distinct IDs from one person to another
     */
    moveDistinctIds(source: InternalPerson, target: InternalPerson, distinctId: string): Promise<MoveDistinctIdsResult>

    /**
     * Updates cohorts and feature flags for merged persons
     */
    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        distinctId: string
    ): Promise<void>

    /**
     * Adds a personless distinct ID during merge
     */
    addPersonlessDistinctIdForMerge(teamId: number, distinctId: string): Promise<boolean>
}
