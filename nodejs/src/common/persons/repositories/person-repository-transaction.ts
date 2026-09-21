import { DateTime } from 'luxon'

import { PersonMessage } from '~/common/persons/person-message'
import { LifecycleMarkPerson } from '~/common/persons/repositories/person-repository'
import { CreatePersonResult, MoveDistinctIdsResult } from '~/common/utils/db/db'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson, PersonUpdateFields, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '~/types'

export interface PersonRepositoryTransaction {
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
    ): Promise<CreatePersonResult>

    updatePerson(
        person: InternalPerson,
        update: PersonUpdateFields,
        tag?: string
    ): Promise<[InternalPerson, PersonMessage[], boolean]>

    deletePerson(person: InternalPerson): Promise<PersonMessage[]>

    /** Batched deletePerson for folded merges; all persons must belong to one team. */
    deletePersons(persons: InternalPerson[]): Promise<PersonMessage[]>

    /** See PersonRepository.claimLifecycleMarks; the marks are held until this transaction commits. */
    claimLifecycleMarks(opId: string, teamId: number, persons: LifecycleMarkPerson[]): Promise<void>

    /** See PersonRepository.releaseLifecycleMarks. */
    releaseLifecycleMarks(opId: string, teamId: number): Promise<void>

    /** See PersonRepository.isPersonLive; only meaningful while holding the person's mark. */
    isPersonLive(person: InternalPerson): Promise<boolean>

    addDistinctId(person: InternalPerson, distinctId: string, version: number): Promise<PersonMessage[]>

    moveDistinctIds(source: InternalPerson, target: InternalPerson, limit?: number): Promise<MoveDistinctIdsResult>

    /** Batched unlimited moveDistinctIds for folded merges; zero moved rows for a source is not a failure. */
    moveDistinctIdsFromPersons(sources: InternalPerson[], target: InternalPerson): Promise<MoveDistinctIdsResult>

    /** Distinct-id counts per person id (single team), for the folded-merge limit pre-check. */
    countDistinctIdsForPersons(teamId: Team['id'], personIds: InternalPerson['id'][]): Promise<Map<string, number>>

    fetchPersonDistinctIds(person: InternalPerson, limit?: number): Promise<string[]>

    updateCohortsAndFeatureFlagsForMerge(
        teamId: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id']
    ): Promise<void>

    updateCohortsAndFeatureFlagsForMergeBatch(
        teamId: Team['id'],
        sourcePersonIDs: InternalPerson['id'][],
        targetPersonID: InternalPerson['id']
    ): Promise<void>
}
