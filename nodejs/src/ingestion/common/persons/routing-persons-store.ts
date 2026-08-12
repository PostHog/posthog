import { DateTime } from 'luxon'

import { personhogStoreShadowErrorsCounter, personhogStoreShadowSkipsCounter } from '~/common/persons/metrics'
import { PersonMessage } from '~/common/persons/person-message'
import { InternalPersonWithDistinctId, LifecycleMarkPerson } from '~/common/persons/repositories/person-repository'
import { PersonRepositoryTransaction } from '~/common/persons/repositories/person-repository-transaction'
import { CreatePersonResult, MoveDistinctIdsResult } from '~/common/utils/db/db'
import { logger } from '~/common/utils/logger'
import { BatchWritingStoreFlushStats } from '~/ingestion/common/stores/batch-writing-store'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '~/types'

import { EventOps } from './person-update'
import { PersonhogPersonsStore } from './personhog-persons-store'
import { FlushResult, PersonsStore } from './persons-store'
import { BatchBoundPersonsStore, PersonsStoreForBatch } from './persons-store-for-batch'
import { PersonsStoreTransaction } from './persons-store-transaction'

export type PersonsStoreMode = 'pg' | 'personhog' | 'shadow'

export function parsePersonsStoreMode(raw: string): PersonsStoreMode {
    if (raw === 'pg' || raw === 'personhog' || raw === 'shadow') {
        return raw
    }
    throw new Error(`PERSONS_STORE_MODE must be pg, personhog, or shadow; got ${JSON.stringify(raw)}`)
}

/**
 * Fails startup when a non-pg mode is missing the endpoints it dials,
 * so a misconfiguration is one loud boot error instead of every write
 * failing at its first RPC.
 */
export function assertPersonsStoreModeConfig(
    mode: PersonsStoreMode,
    addrs: { routerAddr: string; identityAddr: string }
): void {
    if (mode === 'pg') {
        return
    }
    const missing = [
        ...(addrs.routerAddr ? [] : ['PERSONHOG_ADDR']),
        ...(addrs.identityAddr ? [] : ['PERSONHOG_IDENTITY_ADDR']),
    ]
    if (missing.length > 0) {
        throw new Error(`PERSONS_STORE_MODE=${mode} requires ${missing.join(' and ')} to be set`)
    }
}

/**
 * Routes person-store verbs between the Postgres world and the personhog
 * world by team. The mode applies to the teams in `teams` (every team
 * when null); everything else stays on Postgres. In shadow the Postgres
 * result is authoritative and the personhog side runs the same verb
 * afterwards, its failures counted and logged but never failing the
 * batch.
 *
 * Two verb families do not route:
 *
 * - Merge execution has no personhog support until the merge saga
 *   lands: pg and shadow teams run it on Postgres as before, and a
 *   personhog-routed team fails loudly at the first merge mutation —
 *   its reads and writes live in the personhog world, whose row ids
 *   mean nothing to Postgres, so quietly running the merge there would
 *   mutate whatever rows happen to share the numbers. Any non-merge
 *   verb invoked under a Postgres transaction still goes to Postgres
 *   (see `route`).
 * - `personPropertiesSize` routes by mode but is not shadowed: the
 *   personhog store answers it with a constant because the leader
 *   enforces the size ceiling at admission.
 */
export class RoutingPersonsStore implements PersonsStore {
    constructor(
        private pg: PersonsStore,
        private personhog: PersonhogPersonsStore,
        private mode: 'personhog' | 'shadow'
    ) {}

    /**
     * Run the personhog side of a shadowed verb: sequential, awaited, and
     * never allowed to fail the batch.
     */
    private async shadowed(verb: string, run: () => Promise<unknown>): Promise<void> {
        try {
            await run()
        } catch (error) {
            personhogStoreShadowErrorsCounter.labels({ verb }).inc()
            logger.warn('personhog shadow verb failed', { verb, error: String(error) })
        }
    }

    /**
     * The whole mode semantics, once: pg teams run the pg call, personhog
     * teams the personhog call, shadow teams run pg as the authoritative
     * result and the personhog call after it, swallowed. A verb invoked
     * under a Postgres transaction is the merge flow's and stays on pg
     * regardless of team. The two lambdas are each verb's signature
     * adapter — the stores disagree on tx and batchId parameters.
     */
    private async route<T>(
        verb: string,
        teamId: number,
        pg: () => Promise<T>,
        personhog: () => Promise<T>,
        opts?: { tx?: unknown; shadow?: () => Promise<unknown> }
    ): Promise<T> {
        const mode = opts?.tx ? 'pg' : this.mode
        if (mode === 'personhog') {
            return personhog()
        }
        const result = await pg()
        if (mode === 'shadow') {
            await this.shadowed(verb, opts?.shadow ?? personhog)
        }
        return result
    }

    /**
     * Resolve the personhog world's own person for a shadowed write. The
     * caller holds the Postgres row, whose numeric id means nothing in
     * the personhog world — the two id sequences are independent — so a
     * shadow write must re-resolve by distinct id and skip, counted,
     * when the person does not exist there yet. The fetch memoizes per
     * batch, so repeated writes to one person cost one resolution.
     */
    private async withShadowPerson(
        verb: string,
        teamId: number,
        distinctId: string,
        batchId: number,
        run: (person: InternalPerson) => Promise<unknown>
    ): Promise<void> {
        const shadowPerson = await this.personhog.fetchForUpdate(teamId, distinctId, batchId)
        if (shadowPerson === null) {
            personhogStoreShadowSkipsCounter.labels({ verb }).inc()
            return
        }
        await run(shadowPerson)
    }

    forBatch(batchId: number): PersonsStoreForBatch {
        return new BatchBoundPersonsStore(this, batchId)
    }

    /**
     * Routes by mode like every other verb; the callback runs exactly
     * once, so shadow mode delegates to Postgres alone rather than
     * executing it a second time against the personhog store. In
     * personhog mode the store's own placeholder answers until the
     * merge saga lands.
     */
    inTransaction<T>(description: string, transaction: (tx: PersonsStoreTransaction) => Promise<T>): Promise<T> {
        return this.mode === 'personhog'
            ? this.personhog.inTransaction(description, transaction)
            : this.pg.inTransaction(description, transaction)
    }

    fetchForChecking(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null> {
        return this.route(
            'fetchForChecking',
            teamId,
            () => this.pg.fetchForChecking(teamId, distinctId, batchId),
            () => this.personhog.fetchForChecking(teamId, distinctId, batchId)
        )
    }

    fetchForUpdate(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null> {
        return this.route(
            'fetchForUpdate',
            teamId,
            () => this.pg.fetchForUpdate(teamId, distinctId, batchId),
            () => this.personhog.fetchForUpdate(teamId, distinctId, batchId)
        )
    }

    fetchPersonsForUpdateByDistinctIds(
        teamId: number,
        distinctIds: string[],
        batchId: number
    ): Promise<InternalPersonWithDistinctId[]> {
        // Merge-fold pre-lock: merge flows stay whole on Postgres.
        return this.pg.fetchPersonsForUpdateByDistinctIds(teamId, distinctIds, batchId)
    }

    createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        primaryDistinctId: { distinctId: string; version?: number },
        extraDistinctIds: { distinctId: string; version?: number }[] | undefined,
        tx: PersonRepositoryTransaction | undefined,
        batchId: number
    ): Promise<CreatePersonResult> {
        return this.route(
            'createPerson',
            teamId,
            () =>
                this.pg.createPerson(
                    createdAt,
                    properties,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation,
                    teamId,
                    isUserId,
                    isIdentified,
                    uuid,
                    primaryDistinctId,
                    extraDistinctIds,
                    tx,
                    batchId
                ),
            () =>
                this.personhog.createPerson(
                    createdAt,
                    properties,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation,
                    teamId,
                    isUserId,
                    isIdentified,
                    uuid,
                    primaryDistinctId,
                    extraDistinctIds,
                    tx,
                    batchId
                ),
            { tx }
        )
    }

    applyEventOps(
        person: InternalPerson,
        ops: EventOps,
        distinctId: string,
        batchId: number
    ): Promise<[InternalPerson, PersonMessage[]]> {
        return this.route(
            'applyEventOps',
            person.team_id,
            () => this.pg.applyEventOps(person, ops, distinctId, batchId),
            () => this.personhog.applyEventOps(person, ops, distinctId, batchId),
            {
                shadow: () =>
                    this.withShadowPerson('applyEventOps', person.team_id, distinctId, batchId, (shadowPerson) =>
                        this.personhog.applyEventOps(shadowPerson, ops, distinctId, batchId)
                    ),
            }
        )
    }

    updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string,
        batchId: number,
        forceUpdate?: boolean,
        tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        return this.route(
            'updatePersonWithPropertiesDiffForUpdate',
            person.team_id,
            () =>
                this.pg.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    propertiesToSet,
                    propertiesToUnset,
                    otherUpdates,
                    distinctId,
                    batchId,
                    forceUpdate,
                    tx
                ),
            () =>
                this.personhog.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    propertiesToSet,
                    propertiesToUnset,
                    otherUpdates,
                    distinctId,
                    batchId,
                    forceUpdate,
                    tx
                ),
            {
                tx,
                shadow: () =>
                    this.withShadowPerson(
                        'updatePersonWithPropertiesDiffForUpdate',
                        person.team_id,
                        distinctId,
                        batchId,
                        (shadowPerson) =>
                            this.personhog.updatePersonWithPropertiesDiffForUpdate(
                                shadowPerson,
                                propertiesToSet,
                                propertiesToUnset,
                                otherUpdates,
                                distinctId,
                                batchId,
                                forceUpdate
                            )
                    ),
            }
        )
    }

    deletePerson(
        person: InternalPerson,
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<PersonMessage[]> {
        return this.route(
            'deletePerson',
            person.team_id,
            () => this.pg.deletePerson(person, distinctId, tx),
            () => this.personhog.deletePerson(person, distinctId, tx)
        )
    }

    claimLifecycleMarks(
        opId: string,
        teamId: number,
        persons: LifecycleMarkPerson[],
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<void> {
        return this.route(
            'claimLifecycleMarks',
            teamId,
            () => this.pg.claimLifecycleMarks(opId, teamId, persons, distinctId, tx),
            () => this.personhog.claimLifecycleMarks(opId, teamId, persons, distinctId, tx)
        )
    }

    releaseLifecycleMarks(
        opId: string,
        teamId: number,
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<void> {
        return this.route(
            'releaseLifecycleMarks',
            teamId,
            () => this.pg.releaseLifecycleMarks(opId, teamId, distinctId, tx),
            () => this.personhog.releaseLifecycleMarks(opId, teamId, distinctId, tx)
        )
    }

    isPersonLive(person: InternalPerson, distinctId: string, tx?: PersonRepositoryTransaction): Promise<boolean> {
        return this.route(
            'isPersonLive',
            person.team_id,
            () => this.pg.isPersonLive(person, distinctId, tx),
            () => this.personhog.isPersonLive(person, distinctId, tx)
        )
    }

    updatePersonForMerge(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        distinctId: string,
        batchId: number,
        tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        return this.route(
            'updatePersonForMerge',
            person.team_id,
            () => this.pg.updatePersonForMerge(person, update, distinctId, batchId, tx),
            () => this.personhog.updatePersonForMerge(person, update, distinctId, batchId, tx)
        )
    }

    addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx: PersonRepositoryTransaction | undefined,
        batchId: number
    ): Promise<PersonMessage[]> {
        return this.route(
            'addDistinctId',
            person.team_id,
            () => this.pg.addDistinctId(person, distinctId, version, tx, batchId),
            () => this.personhog.addDistinctId(person, distinctId, version, tx, batchId)
        )
    }

    moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        distinctId: string,
        limit: number | undefined,
        tx: PersonRepositoryTransaction,
        batchId: number
    ): Promise<MoveDistinctIdsResult> {
        return this.route(
            'moveDistinctIds',
            source.team_id,
            () => this.pg.moveDistinctIds(source, target, distinctId, limit, tx, batchId),
            () => this.personhog.moveDistinctIds(source, target, distinctId, limit, tx, batchId)
        )
    }

    moveDistinctIdsFromPersons(
        sources: InternalPerson[],
        target: InternalPerson,
        distinctId: string,
        tx: PersonRepositoryTransaction,
        batchId: number
    ): Promise<MoveDistinctIdsResult> {
        return this.route(
            'moveDistinctIdsFromPersons',
            target.team_id,
            () => this.pg.moveDistinctIdsFromPersons(sources, target, distinctId, tx, batchId),
            () => this.personhog.moveDistinctIdsFromPersons(sources, target, distinctId, tx, batchId)
        )
    }

    deletePersons(
        persons: InternalPerson[],
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<PersonMessage[]> {
        if (persons.length === 0) {
            return this.pg.deletePersons(persons, distinctId, tx)
        }
        return this.route(
            'deletePersons',
            persons[0].team_id,
            () => this.pg.deletePersons(persons, distinctId, tx),
            () => this.personhog.deletePersons(persons, distinctId, tx)
        )
    }

    countDistinctIdsForPersons(
        teamId: Team['id'],
        personIds: InternalPerson['id'][],
        distinctId: string,
        tx: PersonRepositoryTransaction
    ): Promise<Map<string, number>> {
        return this.route(
            'countDistinctIdsForPersons',
            teamId,
            () => this.pg.countDistinctIdsForPersons(teamId, personIds, distinctId, tx),
            () => this.personhog.countDistinctIdsForPersons(teamId, personIds, distinctId, tx)
        )
    }

    updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<void> {
        return this.route(
            'updateCohortsAndFeatureFlagsForMerge',
            teamID,
            () => this.pg.updateCohortsAndFeatureFlagsForMerge(teamID, sourcePersonID, targetPersonID, distinctId, tx),
            () =>
                this.personhog.updateCohortsAndFeatureFlagsForMerge(
                    teamID,
                    sourcePersonID,
                    targetPersonID,
                    distinctId,
                    tx
                )
        )
    }

    updateCohortsAndFeatureFlagsForMergeBatch(
        teamID: Team['id'],
        sourcePersonIDs: InternalPerson['id'][],
        targetPersonID: InternalPerson['id'],
        distinctId: string,
        tx?: PersonRepositoryTransaction
    ): Promise<void> {
        return this.route(
            'updateCohortsAndFeatureFlagsForMergeBatch',
            teamID,
            () =>
                this.pg.updateCohortsAndFeatureFlagsForMergeBatch(
                    teamID,
                    sourcePersonIDs,
                    targetPersonID,
                    distinctId,
                    tx
                ),
            () =>
                this.personhog.updateCohortsAndFeatureFlagsForMergeBatch(
                    teamID,
                    sourcePersonIDs,
                    targetPersonID,
                    distinctId,
                    tx
                )
        )
    }

    fetchPersonDistinctIds(
        person: InternalPerson,
        distinctId: string,
        limit: number | undefined,
        tx: PersonRepositoryTransaction
    ): Promise<string[]> {
        return this.route(
            'fetchPersonDistinctIds',
            person.team_id,
            () => this.pg.fetchPersonDistinctIds(person, distinctId, limit, tx),
            () => this.personhog.fetchPersonDistinctIds(person, distinctId, limit, tx)
        )
    }

    personPropertiesSize(personId: string, teamId: number): Promise<number> {
        return this.mode === 'personhog'
            ? this.personhog.personPropertiesSize(personId, teamId)
            : this.pg.personPropertiesSize(personId, teamId)
    }

    removeDistinctIdFromCache(teamId: number, distinctId: string): void {
        this.pg.removeDistinctIdFromCache(teamId, distinctId)
        this.personhog.removeDistinctIdFromCache(teamId, distinctId)
    }

    async prefetchPersons(teamDistinctIds: { teamId: number; distinctId: string; batchId: number }[]): Promise<void> {
        if (this.mode === 'shadow') {
            await this.pg.prefetchPersons(teamDistinctIds)
        }
        await this.shadowedOrDirect('prefetchPersons', () => this.personhog.prefetchPersons(teamDistinctIds))
    }

    /**
     * The personhog side of a fan-out: swallowed in shadow, propagated in
     * personhog mode, where the store is authoritative and redelivery is
     * the retry.
     */
    private async shadowedOrDirect(verb: string, run: () => Promise<unknown>): Promise<void> {
        if (this.mode === 'shadow') {
            await this.shadowed(verb, run)
        } else {
            await run()
        }
    }

    getFlushStats(): BatchWritingStoreFlushStats {
        return this.pg.getFlushStats()
    }

    async flush(): Promise<FlushResult[]> {
        const results = await this.pg.flush()
        await this.shadowedOrDirect('flush', () => this.personhog.flush())
        return results
    }

    releaseBatch(batchId: number): void {
        this.pg.releaseBatch(batchId)
        this.personhog.releaseBatch(batchId)
    }

    async shutdown(): Promise<void> {
        try {
            await this.pg.shutdown()
        } finally {
            await this.personhog.shutdown()
        }
    }
}
