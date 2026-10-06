import { DateTime } from 'luxon'

import { INGESTION_WARNINGS_OUTPUT } from '~/common/outputs'
import { PersonDistinctIdsOutput, PersonMergeEventsOutput, PersonsOutput } from '~/common/outputs'
import { FILTERED_PERSON_UPDATE_PROPERTIES } from '~/common/persons/person-property-utils'
import { PersonUpdate } from '~/common/persons/person-update-batch'
import { PersonPropertiesSizeViolationError, PersonRepository } from '~/common/persons/repositories/person-repository'
import { NoRowsUpdatedError, UUIDT } from '~/common/utils/utils'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'
import { InternalPerson } from '~/types'

import { BatchWritingPersonsStore } from './batch-writing-person-store'
import { createDefaultSyncMergeMode } from './person-merge-types'
import { EventOps } from './person-update'
import { MergePersonsRequest } from './persons-store'

type Held = { label: string; deliver: () => void }

/**
 * Rows with the per-key statement's semantics under a transaction that rolls back on a throw. With
 * `deferStatements` the batch statement evaluates its rows when the held answer is released, as a statement
 * blocked on a merge's row lock does.
 */
class FakeRepository {
    rows = new Map<string, InternalPerson>()
    distinctToUuid = new Map<string, string>()
    held: Held[] = []
    holdFetches = false
    deferStatements = false
    deleteFailures: unknown[] = []
    writes: string[] = []
    private nextId = 1

    addPerson(uuid: string, distinctIds: string[], properties: Record<string, unknown>): InternalPerson {
        const row: InternalPerson = {
            id: String(this.nextId++),
            uuid,
            team_id: 1,
            properties: { ...properties },
            properties_last_updated_at: {},
            properties_last_operation: {},
            created_at: DateTime.fromISO('2026-01-01T00:00:00Z', { zone: 'utc' }),
            version: 1,
            is_identified: false,
            is_user_id: null,
            last_seen_at: null,
        }
        this.rows.set(uuid, row)
        for (const distinctId of distinctIds) {
            this.distinctToUuid.set(`1:${distinctId}`, uuid)
        }
        return this.snapshot(row)
    }

    release(index = 0): void {
        const [held] = this.held.splice(index, 1)
        held.deliver()
    }

    releaseAll(): void {
        while (this.held.length > 0) {
            this.release(0)
        }
    }

    labels(): string[] {
        return this.held.map((held) => held.label)
    }

    async settle(predicate: () => boolean): Promise<void> {
        for (let i = 0; i < 200 && !predicate(); i++) {
            await new Promise((resolve) => setImmediate(resolve))
        }
        if (!predicate()) {
            throw new Error(`condition never held; held: ${this.labels().join(', ')}`)
        }
    }

    private lookup(teamId: number, distinctId: string): InternalPerson | undefined {
        const uuid = this.distinctToUuid.get(`${teamId}:${distinctId}`)
        const row = uuid === undefined ? undefined : this.rows.get(uuid)
        return row ? this.snapshot(row) : undefined
    }

    private snapshot(row: InternalPerson): InternalPerson {
        return { ...row, properties: { ...row.properties } }
    }

    private deliver<T>(hold: boolean, label: string, value: () => T): Promise<T> {
        if (!hold) {
            return Promise.resolve(value())
        }
        return new Promise((resolve) => this.held.push({ label, deliver: () => resolve(value()) }))
    }

    /** Read at call time, answered at release: a read that began before a merge returns the source. */
    fetchPerson = jest.fn((teamId: number, distinctId: string) => {
        const person = this.lookup(teamId, distinctId)
        return this.deliver(this.holdFetches, `fetch:${distinctId}`, () => person)
    })

    fetchPersonsByDistinctIds = jest.fn((keys: { teamId: number; distinctId: string }[]) =>
        this.deliver(this.holdFetches, `prefetch:${keys.map((key) => key.distinctId).join(',')}`, () =>
            keys.flatMap(({ teamId, distinctId }) => {
                const person = this.lookup(teamId, distinctId)
                return person ? [{ ...person, distinct_id: distinctId }] : []
            })
        )
    )

    fetchPersonsForUpdateByDistinctIds = jest.fn((teamId: number, distinctIds: string[]) =>
        this.deliver(this.holdFetches, `fetchForUpdate:${distinctIds.join(',')}`, () =>
            distinctIds.flatMap((distinctId) => {
                const person = this.lookup(teamId, distinctId)
                return person ? [{ ...person, distinct_id: distinctId }] : []
            })
        )
    )

    private applyBatch(updates: PersonUpdate[]): Map<string, unknown> {
        const results = new Map<string, unknown>()
        for (const update of updates) {
            this.writes.push(
                `write ${update.uuid} set=${JSON.stringify(update.properties_to_set)} setOnce=${JSON.stringify(update.properties_to_set_once)} unset=${JSON.stringify(update.properties_to_unset)}`
            )
            if (results.has(update.uuid)) {
                continue
            }
            const row = this.rows.get(update.uuid)
            if (!row || row.team_id !== update.team_id) {
                results.set(update.uuid, { success: false, error: new NoRowsUpdatedError(`no row ${update.uuid}`) })
                continue
            }
            const properties = { ...update.properties_to_set_once, ...row.properties, ...update.properties_to_set }
            for (const key of update.properties_to_unset) {
                delete properties[key]
            }
            row.properties = properties
            row.is_identified = row.is_identified || update.is_identified
            row.created_at = DateTime.min(row.created_at, update.created_at)
            if (update.last_seen_at && (!row.last_seen_at || update.last_seen_at > row.last_seen_at)) {
                row.last_seen_at = update.last_seen_at
            }
            row.version += 1
            results.set(update.uuid, {
                success: true,
                version: row.version,
                kafkaMessage: {},
                person: this.snapshot(row),
            })
        }
        return results
    }

    updatePersonsBatch = jest.fn((updates: PersonUpdate[]) => {
        const label = `write:${updates.map((update) => update.uuid).join(',')}`
        if (this.deferStatements) {
            return this.deliver(true, label, () => this.applyBatch(updates))
        }
        const results = this.applyBatch(updates)
        return this.deliver(false, label, () => results)
    })

    handleOversizedPersonProperties = jest.fn()
    personPropertiesSize = jest.fn().mockResolvedValue(0)
    fetchPersonDistinctIdMappings = jest.fn().mockResolvedValue([])

    inTransaction = jest.fn(async (_description: string, body: (tx: unknown) => Promise<unknown>) => {
        const rowsBefore = new Map([...this.rows].map(([uuid, row]) => [uuid, this.snapshot(row)]))
        const idsBefore = new Map(this.distinctToUuid)
        try {
            return await body(this.tx)
        } catch (error) {
            this.rows = rowsBefore
            this.distinctToUuid = idsBefore
            throw error
        }
    })

    tx = {
        claimLifecycleMarks: jest.fn().mockResolvedValue(undefined),
        releaseLifecycleMarks: jest.fn().mockResolvedValue(undefined),
        isPersonLive: jest.fn().mockResolvedValue(true),
        /** The merge's own statement: its rows are locked by the merge, so it answers at once. */
        updatePersonsBatch: jest.fn((updates: PersonUpdate[]) => Promise.resolve(this.applyBatch(updates))),
        readMergeRows: jest.fn((teamId: number, targetId: string, sourceIds: string[]) =>
            Promise.resolve(
                [...this.rows.values()]
                    .filter((row) => row.team_id === teamId && (row.id === targetId || sourceIds.includes(row.id)))
                    .map((row) => this.snapshot(row))
            )
        ),
        moveDistinctIds: jest.fn((source: InternalPerson, target: InternalPerson) => {
            const moved: string[] = []
            for (const [key, uuid] of this.distinctToUuid) {
                if (uuid === source.uuid) {
                    this.distinctToUuid.set(key, target.uuid)
                    moved.push(key.slice(key.indexOf(':') + 1))
                }
            }
            if (moved.length === 0) {
                return Promise.resolve({ success: false, error: 'SourceNotFound' })
            }
            return Promise.resolve({ success: true, messages: [], distinctIdsMoved: moved })
        }),
        moveDistinctIdsFromPersons: jest.fn(),
        updateCohortsAndFeatureFlagsForMerge: jest.fn().mockResolvedValue(undefined),
        updateCohortsAndFeatureFlagsForMergeBatch: jest.fn().mockResolvedValue(undefined),
        deletePerson: jest.fn((person: InternalPerson) => {
            const failure = this.deleteFailures.shift()
            if (failure) {
                return Promise.reject(failure)
            }
            this.rows.delete(person.uuid)
            return Promise.resolve([])
        }),
        deletePersons: jest.fn(),
        addDistinctId: jest.fn().mockResolvedValue([]),
        fetchPersonDistinctIds: jest.fn().mockResolvedValue([]),
        countDistinctIdsForPersons: jest.fn(),
        createPerson: jest.fn(),
    }
}

const setOps = (set: Record<string, unknown>, unset: string[] = []): EventOps => ({
    set,
    setOnce: {},
    unset,
    denied: false,
    shouldForceUpdate: true,
    eventName: '$set',
})

function mergeRequest(
    targetDistinctId: string,
    sourceDistinctId: string,
    set: Record<string, unknown> = {}
): MergePersonsRequest {
    const eventUuid = new UUIDT().toString()
    return {
        teamId: 1,
        targetDistinctId,
        sources: [{ distinctId: sourceDistinctId, eventUuid }],
        eventOps: { set, setOnce: {}, unset: [], denied: false, shouldForceUpdate: true, eventName: '$identify' },
        eventUuid,
        allowIdentifiedSources: true,
        mergeMode: createDefaultSyncMergeMode(),
        createdAtMs: DateTime.fromISO('2026-02-01T00:00:00Z').toMillis(),
    }
}

const makeOutputs = () =>
    createMockIngestionOutputs<
        PersonsOutput | PersonDistinctIdsOutput | typeof INGESTION_WARNINGS_OUTPUT | PersonMergeEventsOutput
    >()

describe('BatchWritingPersonsStore merging through PostgresPersonMerge', () => {
    let fake: FakeRepository
    let outputs: ReturnType<typeof makeOutputs>
    let store: BatchWritingPersonsStore

    beforeEach(() => {
        fake = new FakeRepository()
        outputs = makeOutputs()
        store = new BatchWritingPersonsStore(fake as unknown as PersonRepository, outputs, {
            optimisticUpdateRetryInterval: 1,
        })
    })

    afterEach(async () => {
        fake.holdFetches = false
        fake.deferStatements = false
        fake.releaseAll()
        try {
            await store.flush()
        } catch {
            // a test may leave a write that cannot land
        }
        try {
            await store.shutdown()
        } catch {
            // a test may leave the cache dirty
        }
    })

    it.each([
        ['set', {}, setOps({ k: 'A' })],
        ['unset', { k: 'old' }, setOps({}, ['k'])],
    ])(
        "a flush statement blocked behind this pod's merge does not re-target the source's pre-merge %s over the survivor",
        async (_lane, sourceProperties, ops) => {
            fake.addPerson('T', ['t'], { k: 'B' })
            fake.addPerson('S', ['s'], sourceProperties)
            const source = await store.fetchForUpdate(1, 's', 0)
            await store.fetchForUpdate(1, 't', 0)
            await store.applyEventOps(source!, ops, 's', 0)
            // The statement waits on the source's lock; the merge reads the source's pending change, sees the
            // survivor holds the key, and decides the survivor wins.
            fake.deferStatements = true
            const flushing = store.flush()
            await fake.settle(() => fake.labels().length === 1)
            const result = await store.mergePersons(mergeRequest('t', 's'), 0)
            expect(result.results[0].outcome).toBe('merged')
            fake.deferStatements = false
            fake.releaseAll()
            await flushing

            await store.flush()

            expect(fake.rows.get('S')).toBeUndefined()
            expect(fake.rows.get('T')!.properties).toEqual({ k: 'B' })
        }
    )

    it("an identify's $set of a filtered key lands on an already identified survivor", async () => {
        const filtered = [...FILTERED_PERSON_UPDATE_PROPERTIES][0]
        fake.addPerson('T', ['t'], { [filtered]: 'old' })
        fake.rows.get('T')!.is_identified = true
        fake.addPerson('S', ['s'], {})
        await store.fetchForUpdate(1, 's', 0)
        await store.fetchForUpdate(1, 't', 0)
        // The merge queues the event's $set as a set the flush would ignore on its own; the event's ops then
        // apply to the survivor, as the processor does after a merge.
        const request = mergeRequest('t', 's', { [filtered]: 'v' })
        const result = await store.mergePersons(request, 0)
        await store.applyEventOps(result.survivor!, request.eventOps, 't', 0)

        await store.flush()

        expect(fake.rows.get('T')!.properties).toEqual({ [filtered]: 'v' })
    })

    it('an explicit $set on a moved id during the merge reaches the survivor although it holds the key', async () => {
        fake.addPerson('T', ['t'], { k: 'B' })
        fake.addPerson('S', ['s'], {})
        await store.fetchForUpdate(1, 's', 0)
        await store.fetchForUpdate(1, 't', 0)
        // Between the move and the outcome read, on an id the store already maps.
        const moveDistinctIds = store.moveDistinctIds.bind(store)
        jest.spyOn(store, 'moveDistinctIds').mockImplementationOnce(async (...args) => {
            const moved = await moveDistinctIds(...args)
            const person = await store.fetchForUpdate(1, 's', 0)
            await store.applyEventOps(person!, setOps({ k: 'v' }), 's', 0)
            return moved
        })
        const result = await store.mergePersons(mergeRequest('t', 's'), 0)
        expect(result.results[0].outcome).toBe('merged')

        await store.flush()

        expect(fake.rows.get('T')!.properties).toEqual({ k: 'v' })
    })

    it("a chained re-target keeps the last_seen_at the first hop carried when the survivor's entry is gone", async () => {
        const seen = DateTime.fromISO('2026-03-01T00:00:00Z', { zone: 'utc' })
        fake.addPerson('P1', ['a'], {})
        fake.addPerson('P2', ['b'], {})
        fake.addPerson('P3', ['c'], {})
        const p1 = await store.fetchForUpdate(1, 'a', 0)
        await store.applyEventOps(p1!, setOps({ k: 'A' }), 'a', 0)
        await store.updatePersonWithPropertiesDiffForUpdate(p1!, {}, [], { last_seen_at: seen }, 'a')
        // Another pod merged P1 into P2; this pod never cached P2.
        fake.distinctToUuid.set('1:a', 'P2')
        fake.rows.delete('P1')
        fake.deferStatements = true
        const flushing = store.flush()
        await fake.settle(() => fake.labels().length === 1)
        fake.release(0)
        await fake.settle(() => fake.labels().length === 1)
        fake.release(0)
        await fake.settle(() => fake.labels().length === 1)
        expect(fake.labels()).toEqual(['write:P2'])
        // P2 is merged into P3 while that write waits.
        fake.distinctToUuid.set('1:a', 'P3')
        fake.distinctToUuid.set('1:b', 'P3')
        fake.rows.delete('P2')
        fake.deferStatements = false
        fake.release(0)
        await flushing

        const landed = fake.updatePersonsBatch.mock.calls.flat(2).find((update) => update.uuid === 'P3')
        expect(landed?.last_seen_at?.toISO()).toBe(seen.toISO())
    })

    it('a re-target whose survivor is merged away in turn lands on the final survivor', async () => {
        fake.addPerson('P1', ['a'], {})
        fake.addPerson('P2', ['b'], {})
        fake.addPerson('P3', ['c'], {})
        const p1 = await store.fetchForUpdate(1, 'a', 0)
        await store.fetchForUpdate(1, 'b', 0)
        // Another pod merged P1 into P2; this pod still holds P1's entry.
        fake.distinctToUuid.set('1:a', 'P2')
        fake.rows.delete('P1')
        await store.applyEventOps(p1!, setOps({ k: 'A' }), 'a', 0)
        fake.deferStatements = true
        const flushing = store.flush()
        // The statement finds no row for P1, the record retries alone and finds none again, and the re-target
        // onto P2 waits while another pod merges P2 into P3.
        await fake.settle(() => fake.labels().length === 1)
        fake.release(0)
        await fake.settle(() => fake.labels().length === 1)
        fake.release(0)
        await fake.settle(() => fake.labels().length === 1)
        expect(fake.labels()).toEqual(['write:P2'])
        fake.distinctToUuid.set('1:a', 'P3')
        fake.distinctToUuid.set('1:b', 'P3')
        fake.rows.delete('P2')
        fake.deferStatements = false
        fake.release(0)
        await flushing

        expect(fake.rows.get('P3')!.properties).toEqual({ k: 'A' })
    })

    it("a merge's outcome is on the row when the pod stops right after the commit", async () => {
        fake.addPerson('T', ['t'], { k: 'B' })
        fake.addPerson('S', ['s'], { a: 1 })
        await store.fetchForUpdate(1, 's', 0)
        await store.fetchForUpdate(1, 't', 0)
        jest.spyOn(store, 'takeMergedRow').mockImplementationOnce(() => {
            throw new Error('pod stopped')
        })

        await expect(store.mergePersons(mergeRequest('t', 's'), 0)).rejects.toThrow('pod stopped')

        expect(fake.rows.get('S')).toBeUndefined()
        expect(fake.rows.get('T')).toMatchObject({ properties: { k: 'B', a: 1 }, is_identified: true })
    })

    it('an oversized survivor rolls the merge back and commits it on a rerun without the outcome, warning once', async () => {
        fake.addPerson('T', ['t'], { k: 'B' })
        fake.addPerson('S', ['s'], { a: 1 })
        await store.fetchForUpdate(1, 's', 0)
        await store.fetchForUpdate(1, 't', 0)
        // As in Postgres, the violation aborts its transaction: any later statement in it fails.
        let abortedTransaction = -1
        fake.tx.updatePersonsBatch.mockImplementationOnce((updates: PersonUpdate[]) => {
            abortedTransaction = fake.inTransaction.mock.calls.length
            return Promise.resolve(
                new Map(
                    updates.map((update) => [
                        update.uuid,
                        { success: false, error: new PersonPropertiesSizeViolationError('too big', 1, update.id) },
                    ])
                )
            )
        })
        const deletePerson = fake.tx.deletePerson.getMockImplementation()!
        fake.tx.deletePerson.mockImplementation((person: InternalPerson) =>
            fake.inTransaction.mock.calls.length === abortedTransaction
                ? Promise.reject(new Error('current transaction is aborted'))
                : deletePerson(person)
        )

        const result = await store.mergePersons(mergeRequest('t', 's'), 0)

        expect(result.results[0].outcome).toBe('merged')
        expect(fake.inTransaction).toHaveBeenCalledTimes(2)
        expect(fake.tx.updatePersonsBatch).toHaveBeenCalledTimes(1)
        expect(fake.rows.get('S')).toBeUndefined()
        expect(fake.distinctToUuid.get('1:s')).toBe('T')
        expect(fake.rows.get('T')!.properties).toEqual({ k: 'B' })
        const warnings = outputs.queueMessages.mock.calls.filter(([output]) => output === INGESTION_WARNINGS_OUTPUT)
        expect(warnings).toHaveLength(1)
        expect(String(warnings[0][1][0].value)).toContain('person_properties_size_violation')
    })

    it("the survivor a merge hands back shows this pod's unflushed changes", async () => {
        fake.addPerson('T', ['t'], { k: 'B' })
        fake.addPerson('S', ['s'], { a: 1 })
        await store.fetchForUpdate(1, 's', 0)
        const target = await store.fetchForUpdate(1, 't', 0)
        await store.applyEventOps(target!, setOps({ p: 'pending' }), 't', 0)

        const result = await store.mergePersons(mergeRequest('t', 's'), 0)

        expect(result.survivor!.properties).toEqual({ k: 'B', a: 1, p: 'pending' })
        expect(fake.rows.get('T')!.properties).toEqual({ k: 'B', a: 1 })
    })

    it('a merge that rolls back leaves nothing of it queued on the survivor', async () => {
        const target = fake.addPerson('T', ['t'], { own: 'x' })
        fake.addPerson('S', ['s', 's2'], { a: 1 })
        await store.fetchForUpdate(1, 's', 0)
        await store.fetchForUpdate(1, 't', 0)
        // The delete fails on a concurrent distinct-id add; the retry finds the source merged elsewhere and
        // settles without merging.
        fake.deleteFailures.push(Object.assign(new Error('fk'), { code: '23503' }))
        const lookup = fake.fetchPerson.getMockImplementation()!
        fake.fetchPerson.mockImplementation((teamId: number, distinctId: string) =>
            distinctId === 's' && fake.tx.deletePerson.mock.calls.length > 0
                ? Promise.resolve(undefined)
                : lookup(teamId, distinctId)
        )

        const result = await store.mergePersons(mergeRequest('t', 's'), 0)

        expect(result.survivor?.uuid).toBe('T')
        expect(fake.rows.get('S')).toBeDefined()
        const entry = store.getCachedPersonForUpdateByPersonId(1, target.id)!
        expect(entry.properties_to_set_once).toEqual({})
        expect(entry.is_identified).toBe(false)
        expect(entry.created_at.toISO()).toBe(target.created_at.toISO())
        // The rollback made the moved ids the source's again, in the cache too.
        expect((await store.fetchForUpdate(1, 's2', 0))!.uuid).toBe('S')
    })

    it('a team off the locked-outcome allowlist queues the survivor for the flush and locks no row', async () => {
        await store.shutdown()
        store = new BatchWritingPersonsStore(fake as unknown as PersonRepository, outputs, {
            optimisticUpdateRetryInterval: 1,
            mergeLockedOutcomeTeamAllowlist: '',
        })
        fake.addPerson('T', ['t'], { k: 'B' })
        fake.addPerson('S', ['s'], { a: 1, k: 'A' })
        await store.fetchForUpdate(1, 's', 0)
        await store.fetchForUpdate(1, 't', 0)

        const result = await store.mergePersons(mergeRequest('t', 's'), 0)

        expect(result.results[0].outcome).toBe('merged')
        expect(result.survivor!.properties).toEqual({ k: 'B', a: 1 })
        expect(fake.tx.readMergeRows).not.toHaveBeenCalled()
        expect(fake.tx.updatePersonsBatch).not.toHaveBeenCalled()
        expect(fake.rows.get('S')).toBeUndefined()
        expect(fake.rows.get('T')!.properties).toEqual({ k: 'B' })

        await store.flush()

        expect(fake.rows.get('T')).toMatchObject({ properties: { k: 'B', a: 1 }, is_identified: true })
    })

    it("a re-target keeps the survivor's newer last_seen_at", async () => {
        const seen = DateTime.fromISO('2026-03-01T00:00:00Z', { zone: 'utc' })
        fake.addPerson('T', ['t'], {})
        fake.rows.get('T')!.last_seen_at = seen
        fake.addPerson('S', ['s'], {})
        fake.rows.get('S')!.last_seen_at = DateTime.fromISO('2026-01-01T00:00:00Z', { zone: 'utc' })
        const source = await store.fetchForUpdate(1, 's', 0)
        await store.applyEventOps(source!, setOps({ k: 'A' }), 's', 0)
        // Another pod merges S into T.
        fake.distinctToUuid.set('1:s', 'T')
        fake.rows.delete('S')

        await store.flush()

        const retargeted = fake.updatePersonsBatch.mock.calls.flat(2).find((update) => update.uuid === 'T')
        expect(retargeted?.last_seen_at?.toISO()).toBe(seen.toISO())
    })

    it('a merge that fails for good leaves no moved distinct id mapped to the survivor', async () => {
        fake.addPerson('T', ['t'], {})
        fake.addPerson('S', ['s1', 's2'], {})
        await store.fetchForUpdate(1, 's1', 0)
        await store.fetchForUpdate(1, 't', 0)
        fake.deleteFailures.push(new Error('connection reset'))

        await expect(store.mergePersons(mergeRequest('t', 's1'), 0)).rejects.toThrow('connection reset')

        expect((await store.fetchForUpdate(1, 's2', 0))!.uuid).toBe('S')
    })
})
