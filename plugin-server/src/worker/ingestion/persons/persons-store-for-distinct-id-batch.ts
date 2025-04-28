import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TopicMessage } from '../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '../../../types'
import { TransactionClient } from '../../../utils/db/postgres'

export interface PersonsStoreForDistinctIdBatch {
    /**
     * Executes a function within a transaction
     * @param description - Description of the transaction for logging
     * @param transaction - Function to execute within the transaction, receives a transaction client
     */
    inTransaction<T>(description: string, transaction: (tx: TransactionClient) => Promise<T>): Promise<T>

    /**
     * Fetches a person by team ID and distinct ID for checking existence
     * Uses read replica when available
     */
    fetchForChecking(teamId: number, distinctId: string): Promise<InternalPerson | null>

    /**
     * Fetches a person by team ID and distinct ID with a row-level lock
     * Always uses primary database
     */
    fetchForUpdate(teamId: number, distinctId: string): Promise<InternalPerson | null>

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
        distinctIds?: { distinctId: string; version?: number }[],
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[]]>

    /**
     * Updates an existing person
     */
    updatePersonDeprecated(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[]]>

    /**
     * Deletes a person
     */
    deletePerson(person: InternalPerson, tx?: TransactionClient): Promise<TopicMessage[]>

    /**
     * Adds a distinct ID to a person
     */
    addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: TransactionClient
    ): Promise<TopicMessage[]>

    /**
     * Moves distinct IDs from one person to another
     */
    moveDistinctIds(source: InternalPerson, target: InternalPerson, tx?: TransactionClient): Promise<TopicMessage[]>

    /**
     * Updates cohorts and feature flags for merged persons
     */
    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        tx?: TransactionClient
    ): Promise<void>

    /**
     * Adds a personless distinct ID
     */
    addPersonlessDistinctId(teamId: number, distinctId: string): Promise<boolean>

    /**
     * Adds a personless distinct ID during merge
     */
    addPersonlessDistinctIdForMerge(teamId: number, distinctId: string, tx?: TransactionClient): Promise<boolean>

    /**
     * Returns the size of the person properties
     */
    personPropertiesSize(teamId: number, distinctId: string): Promise<number>
}
