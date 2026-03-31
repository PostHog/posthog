import { DateTime } from 'luxon'

import { Properties } from '~/plugin-scaffold'

import {
    InternalPerson,
    PersonUpdateFields,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    Team,
    TeamId,
} from '../../types'
import { CreatePersonResult } from '../../utils/db/db'
import { logger } from '../../utils/logger'
import { PersonMessage } from '../../worker/ingestion/persons/person-message'
import { PersonUpdate } from '../../worker/ingestion/persons/person-update-batch'
import {
    InternalPersonWithDistinctId,
    PersonRepository,
} from '../../worker/ingestion/persons/repositories/person-repository'
import { PersonRepositoryTransaction } from '../../worker/ingestion/persons/repositories/person-repository-transaction'
import { PersonHogClient } from './client'
import { personhogErrorsTotal, personhogLatencySeconds, personhogRequestsTotal } from './metrics'

export class PersonHogPersonRepository implements PersonRepository {
    constructor(
        private postgres: PersonRepository,
        private grpcClient: PersonHogClient,
        private grpcPercentage: number,
        private clientLabel: string
    ) {}

    private shouldUseGrpc(): boolean {
        return Math.random() * 100 < this.grpcPercentage
    }

    private async timedPostgres<T>(method: string, fn: () => Promise<T>): Promise<T> {
        const end = personhogLatencySeconds.startTimer({ method, source: 'postgres', client: this.clientLabel })
        try {
            return await fn()
        } finally {
            end()
            personhogRequestsTotal.inc({ method, source: 'postgres', client: this.clientLabel })
        }
    }

    private async timedGrpc<T>(method: string, fn: () => Promise<T>): Promise<T> {
        const end = personhogLatencySeconds.startTimer({ method, source: 'grpc', client: this.clientLabel })
        try {
            const result = await fn()
            return result
        } catch (error) {
            personhogErrorsTotal.inc({ method, client: this.clientLabel })
            throw error
        } finally {
            end()
            personhogRequestsTotal.inc({ method, source: 'grpc', client: this.clientLabel })
        }
    }

    // Read operations — route to gRPC based on percentage

    async fetchPerson(
        teamId: Team['id'],
        distinctId: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean }
    ): Promise<InternalPerson | undefined> {
        // Only route to gRPC for eventually-consistent replica reads
        if (options?.forUpdate || !options?.useReadReplica || !this.shouldUseGrpc()) {
            return this.timedPostgres('fetchPerson', () => this.postgres.fetchPerson(teamId, distinctId, options))
        }

        try {
            const results = await this.timedGrpc('fetchPerson', () =>
                this.grpcClient.persons.fetchPersonsByDistinctIds([{ teamId, distinctId }])
            )
            if (results.length === 0) {
                return undefined
            }
            // Strip distinct_id from the result since fetchPerson returns InternalPerson
            const { distinct_id: _, ...person } = results[0]
            return person
        } catch (error) {
            logger.warn('[PersonHog] gRPC fetchPerson failed, falling back to Postgres', {
                teamId,
                error: String(error),
            })
            return this.timedPostgres('fetchPerson', () => this.postgres.fetchPerson(teamId, distinctId, options))
        }
    }

    async fetchPersonsByDistinctIds(
        teamPersons: { teamId: TeamId; distinctId: string }[],
        useReadReplica?: boolean
    ): Promise<InternalPersonWithDistinctId[]> {
        // Default matches PostgresPersonRepository (useReadReplica=true)
        if (useReadReplica === false || !this.shouldUseGrpc()) {
            return this.timedPostgres('fetchPersonsByDistinctIds', () =>
                this.postgres.fetchPersonsByDistinctIds(teamPersons, useReadReplica)
            )
        }

        try {
            return await this.timedGrpc('fetchPersonsByDistinctIds', () =>
                this.grpcClient.persons.fetchPersonsByDistinctIds(teamPersons)
            )
        } catch (error) {
            logger.warn('[PersonHog] gRPC fetchPersonsByDistinctIds failed, falling back to Postgres', {
                count: teamPersons.length,
                error: String(error),
            })
            return this.timedPostgres('fetchPersonsByDistinctIds', () =>
                this.postgres.fetchPersonsByDistinctIds(teamPersons, useReadReplica)
            )
        }
    }

    async fetchPersonsByPersonIds(
        teamPersons: { teamId: TeamId; personId: string }[],
        useReadReplica?: boolean
    ): Promise<InternalPerson[]> {
        // Default matches PostgresPersonRepository (useReadReplica=true)
        if (useReadReplica === false || !this.shouldUseGrpc()) {
            return this.timedPostgres('fetchPersonsByPersonIds', () =>
                this.postgres.fetchPersonsByPersonIds(teamPersons, useReadReplica)
            )
        }

        try {
            return await this.timedGrpc('fetchPersonsByPersonIds', () =>
                this.grpcClient.persons.fetchPersonsByPersonIds(teamPersons)
            )
        } catch (error) {
            logger.warn('[PersonHog] gRPC fetchPersonsByPersonIds failed, falling back to Postgres', {
                count: teamPersons.length,
                error: String(error),
            })
            return this.timedPostgres('fetchPersonsByPersonIds', () =>
                this.postgres.fetchPersonsByPersonIds(teamPersons, useReadReplica)
            )
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
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        return this.postgres.updatePerson(person, update, tag)
    }

    updatePersonAssertVersion(personUpdate: PersonUpdate): Promise<[number | undefined, PersonMessage[]]> {
        return this.postgres.updatePersonAssertVersion(personUpdate)
    }

    updatePersonsBatch(
        personUpdates: PersonUpdate[]
    ): Promise<Map<string, { success: boolean; version?: number; kafkaMessage?: PersonMessage; error?: Error }>> {
        return this.postgres.updatePersonsBatch(personUpdates)
    }

    deletePerson(person: InternalPerson): Promise<PersonMessage[]> {
        return this.postgres.deletePerson(person)
    }

    addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<PersonMessage[]> {
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
