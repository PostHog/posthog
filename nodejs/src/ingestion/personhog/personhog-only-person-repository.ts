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
import { PersonMessage } from '../../worker/ingestion/persons/person-message'
import { PersonUpdate } from '../../worker/ingestion/persons/person-update-batch'
import {
    InternalPersonWithDistinctId,
    PersonRepository,
} from '../../worker/ingestion/persons/repositories/person-repository'
import { PersonRepositoryTransaction } from '../../worker/ingestion/persons/repositories/person-repository-transaction'
import { PersonHogClient } from './client'
import { timedGrpc } from './metrics'

export class PersonHogOnlyPersonRepository implements PersonRepository {
    constructor(
        private grpcClient: PersonHogClient,
        private clientLabel: string
    ) {}

    async fetchPerson(
        teamId: Team['id'],
        distinctId: string,
        _options?: { forUpdate?: boolean; useReadReplica?: boolean }
    ): Promise<InternalPerson | undefined> {
        const results = await timedGrpc(this.clientLabel, 'fetchPerson', () =>
            this.grpcClient.persons.fetchPersonsByDistinctIds([{ teamId, distinctId }])
        )
        return results.length > 0 ? results[0] : undefined
    }

    async fetchPersonsByDistinctIds(
        teamPersons: { teamId: TeamId; distinctId: string }[],
        _useReadReplica?: boolean
    ): Promise<InternalPersonWithDistinctId[]> {
        return timedGrpc(this.clientLabel, 'fetchPersonsByDistinctIds', () =>
            this.grpcClient.persons.fetchPersonsByDistinctIds(teamPersons)
        )
    }

    async fetchPersonsByPersonIds(
        teamPersons: { teamId: TeamId; personId: string }[],
        _useReadReplica?: boolean
    ): Promise<InternalPerson[]> {
        return timedGrpc(this.clientLabel, 'fetchPersonsByPersonIds', () =>
            this.grpcClient.persons.fetchPersonsByPersonIds(teamPersons)
        )
    }

    // Write operations are not supported — CDP services are read-only consumers.

    createPerson(
        _createdAt: DateTime,
        _properties: Properties,
        _propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        _propertiesLastOperation: PropertiesLastOperation,
        _teamId: Team['id'],
        _isUserId: number | null,
        _isIdentified: boolean,
        _uuid: string,
        _primaryDistinctId: { distinctId: string; version?: number },
        _extraDistinctIds?: { distinctId: string; version?: number }[]
    ): Promise<CreatePersonResult> {
        throw new Error('PersonHogOnlyPersonRepository does not support write operations')
    }

    updatePerson(
        _person: InternalPerson,
        _update: PersonUpdateFields,
        _tag?: string
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        throw new Error('PersonHogOnlyPersonRepository does not support write operations')
    }

    updatePersonAssertVersion(_personUpdate: PersonUpdate): Promise<[number | undefined, PersonMessage[]]> {
        throw new Error('PersonHogOnlyPersonRepository does not support write operations')
    }

    updatePersonsBatch(
        _personUpdates: PersonUpdate[]
    ): Promise<Map<string, { success: boolean; version?: number; kafkaMessage?: PersonMessage; error?: Error }>> {
        throw new Error('PersonHogOnlyPersonRepository does not support write operations')
    }

    deletePerson(_person: InternalPerson): Promise<PersonMessage[]> {
        throw new Error('PersonHogOnlyPersonRepository does not support write operations')
    }

    addDistinctId(_person: InternalPerson, _distinctId: string, _version: number): Promise<PersonMessage[]> {
        throw new Error('PersonHogOnlyPersonRepository does not support write operations')
    }

    addPersonlessDistinctId(_teamId: Team['id'], _distinctId: string): Promise<boolean> {
        throw new Error('PersonHogOnlyPersonRepository does not support write operations')
    }

    addPersonlessDistinctIdForMerge(_teamId: Team['id'], _distinctId: string): Promise<boolean> {
        throw new Error('PersonHogOnlyPersonRepository does not support write operations')
    }

    addPersonlessDistinctIdsBatch(_entries: { teamId: number; distinctId: string }[]): Promise<Map<string, boolean>> {
        throw new Error('PersonHogOnlyPersonRepository does not support write operations')
    }

    personPropertiesSize(_personId: string, _teamId: number): Promise<number> {
        throw new Error('PersonHogOnlyPersonRepository does not support write operations')
    }

    updateCohortsAndFeatureFlagsForMerge(
        _teamID: Team['id'],
        _sourcePersonID: InternalPerson['id'],
        _targetPersonID: InternalPerson['id']
    ): Promise<void> {
        throw new Error('PersonHogOnlyPersonRepository does not support write operations')
    }

    inTransaction<T>(_description: string, _transaction: (tx: PersonRepositoryTransaction) => Promise<T>): Promise<T> {
        throw new Error('PersonHogOnlyPersonRepository does not support write operations')
    }
}
