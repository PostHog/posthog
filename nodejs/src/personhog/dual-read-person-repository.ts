import { DateTime } from 'luxon'

import { Properties } from '~/plugin-scaffold'

import { TopicMessage } from '../kafka/producer'
import {
    InternalPerson,
    PersonUpdateFields,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    Team,
    TeamId,
} from '../types'
import { CreatePersonResult } from '../utils/db/db'
import { logger } from '../utils/logger'
import { PersonUpdate } from '../worker/ingestion/persons/person-update-batch'
import {
    InternalPersonWithDistinctId,
    PersonRepository,
} from '../worker/ingestion/persons/repositories/person-repository'
import { PersonRepositoryTransaction } from '../worker/ingestion/persons/repositories/person-repository-transaction'
import { PersonHogClient } from './client'

export class DualReadPersonRepository implements PersonRepository {
    constructor(
        private postgres: PersonRepository,
        private grpcClient: PersonHogClient,
        private grpcPercentage: number
    ) {}

    private shouldUseGrpc(): boolean {
        return Math.random() * 100 < this.grpcPercentage
    }

    async fetchPerson(
        teamId: Team['id'],
        distinctId: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean }
    ): Promise<InternalPerson | undefined> {
        // Only route to gRPC for replica reads (not forUpdate, and useReadReplica is true)
        if (options?.forUpdate || !options?.useReadReplica || !this.shouldUseGrpc()) {
            return this.postgres.fetchPerson(teamId, distinctId, options)
        }

        try {
            return await this.grpcClient.fetchPersonByDistinctId(teamId, distinctId)
        } catch (error) {
            logger.warn('[PersonHog] gRPC fetchPerson failed, falling back to Postgres', {
                teamId,
                error: String(error),
            })
            return this.postgres.fetchPerson(teamId, distinctId, options)
        }
    }

    async fetchPersonsByDistinctIds(
        teamPersons: { teamId: TeamId; distinctId: string }[],
        useReadReplica: boolean = true
    ): Promise<InternalPersonWithDistinctId[]> {
        if (!useReadReplica || !this.shouldUseGrpc()) {
            return this.postgres.fetchPersonsByDistinctIds(teamPersons, useReadReplica)
        }

        try {
            return await this.grpcClient.fetchPersonsByDistinctIds(teamPersons)
        } catch (error) {
            logger.warn('[PersonHog] gRPC fetchPersonsByDistinctIds failed, falling back to Postgres', {
                count: teamPersons.length,
                error: String(error),
            })
            return this.postgres.fetchPersonsByDistinctIds(teamPersons, useReadReplica)
        }
    }

    async fetchPersonsByPersonIds(
        teamPersons: { teamId: TeamId; personId: string }[],
        useReadReplica: boolean = true
    ): Promise<InternalPerson[]> {
        if (!useReadReplica || !this.shouldUseGrpc()) {
            return this.postgres.fetchPersonsByPersonIds(teamPersons, useReadReplica)
        }

        try {
            return await this.grpcClient.fetchPersonsByUuids(teamPersons)
        } catch (error) {
            logger.warn('[PersonHog] gRPC fetchPersonsByPersonIds failed, falling back to Postgres', {
                count: teamPersons.length,
                error: String(error),
            })
            return this.postgres.fetchPersonsByPersonIds(teamPersons, useReadReplica)
        }
    }

    // All write operations delegate directly to Postgres

    createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        teamId: Team['id'],
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        primaryDistinctId: { distinctId: string; version?: number },
        extraDistinctIds?: { distinctId: string; version?: number }[]
    ): Promise<CreatePersonResult> {
        return this.postgres.createPerson(
            createdAt,
            properties,
            propertiesLastUpdatedAt,
            propertiesLastOperation,
            teamId,
            isUserId,
            isIdentified,
            uuid,
            primaryDistinctId,
            extraDistinctIds
        )
    }

    updatePerson(
        person: InternalPerson,
        update: PersonUpdateFields,
        tag?: string
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        return this.postgres.updatePerson(person, update, tag)
    }

    updatePersonAssertVersion(personUpdate: PersonUpdate): Promise<[number | undefined, TopicMessage[]]> {
        return this.postgres.updatePersonAssertVersion(personUpdate)
    }

    updatePersonsBatch(
        personUpdates: PersonUpdate[]
    ): Promise<Map<string, { success: boolean; version?: number; kafkaMessage?: TopicMessage; error?: Error }>> {
        return this.postgres.updatePersonsBatch(personUpdates)
    }

    deletePerson(person: InternalPerson): Promise<TopicMessage[]> {
        return this.postgres.deletePerson(person)
    }

    addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<TopicMessage[]> {
        return this.postgres.addDistinctId(person, distinctId, version)
    }

    addPersonlessDistinctId(teamId: Team['id'], distinctId: string): Promise<boolean> {
        return this.postgres.addPersonlessDistinctId(teamId, distinctId)
    }

    addPersonlessDistinctIdForMerge(teamId: Team['id'], distinctId: string): Promise<boolean> {
        return this.postgres.addPersonlessDistinctIdForMerge(teamId, distinctId)
    }

    addPersonlessDistinctIdsBatch(entries: { teamId: number; distinctId: string }[]): Promise<Map<string, boolean>> {
        return this.postgres.addPersonlessDistinctIdsBatch(entries)
    }

    personPropertiesSize(personId: string, teamId: number): Promise<number> {
        return this.postgres.personPropertiesSize(personId, teamId)
    }

    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id']
    ): Promise<void> {
        return this.postgres.updateCohortsAndFeatureFlagsForMerge(teamID, sourcePersonID, targetPersonID)
    }

    inTransaction<T>(description: string, transaction: (tx: PersonRepositoryTransaction) => Promise<T>): Promise<T> {
        return this.postgres.inTransaction(description, transaction)
    }
}
