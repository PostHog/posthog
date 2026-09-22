import { DateTime } from 'luxon'

import { INGESTION_WARNINGS_OUTPUT } from '~/common/outputs'
import { PersonDistinctIdsOutput, PersonMergeEventsOutput, PersonsOutput } from '~/common/outputs'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'
import { InternalPerson } from '~/types'

import { BatchWritingPersonsStore } from './batch-writing-person-store'
import { PersonContext } from './person-context'
import { createDefaultSyncMergeMode } from './person-merge-types'
import { PersonPropertyService } from './person-property-service'
import { EventOps } from './person-update'
import { BatchBoundPersonsStore } from './persons-store-for-batch'

jest.mock('~/ingestion/common/ingestion-warnings', () => ({
    emitIngestionWarning: jest.fn().mockResolvedValue(undefined),
}))

const TEAM_ID = 1
const ANON = 'anon-1'
const USER = 'user-1'

function person(id: string, uuid: string, properties: Record<string, unknown> = {}): InternalPerson {
    return {
        id,
        team_id: TEAM_ID,
        uuid,
        properties,
        properties_last_updated_at: {},
        properties_last_operation: {},
        created_at: DateTime.fromISO('2026-01-01T00:00:00Z'),
        version: 1,
        is_user_id: null,
        is_identified: false,
        last_seen_at: null,
    }
}

const setOps = (set: Record<string, unknown>): EventOps =>
    ({ set, setOnce: {}, unset: [], denied: false, shouldForceUpdate: false, eventName: '$pageview' }) as EventOps

describe('a buffered update whose person was merged away by another writer', () => {
    let anon: InternalPerson
    let survivor: InternalPerson
    let repo: any
    let writes: { uuid: string; properties: Record<string, unknown> }[]

    beforeEach(() => {
        anon = person('10', 'anon-uuid')
        survivor = person('20', 'user-uuid', { user_prop: 'kept' })
        writes = []

        // After the merge the anon id resolves to the survivor and the anon row is gone.
        repo = {
            fetchPerson: jest
                .fn()
                .mockImplementation((_team: number, distinctId: string) =>
                    Promise.resolve(distinctId === ANON || distinctId === USER ? survivor : null)
                ),
            fetchPersonsByDistinctIds: jest.fn().mockResolvedValue([]),
            fetchPersonsForUpdateByDistinctIds: jest.fn().mockResolvedValue([]),
            fetchPersonDistinctIds: jest.fn().mockResolvedValue([]),
            fetchPersonDistinctIdMappings: jest.fn().mockResolvedValue([]),
            fetchPersonsByPersonIds: jest.fn().mockResolvedValue([]),
            fetchDistinctIdsForPersons: jest.fn().mockResolvedValue({}),
            personPropertiesSize: jest.fn().mockResolvedValue(0),
            inTransaction: jest.fn().mockImplementation((_d: string, fn: (tx: any) => Promise<unknown>) => fn({})),
            // NO_ASSERT batch path: the anon uuid is not in the result, which the store treats as a failure to retry.
            updatePersonsBatch: jest.fn().mockImplementation((updates: any[]) => {
                const results = new Map()
                for (const update of updates) {
                    if (update.uuid === survivor.uuid) {
                        writes.push({
                            uuid: update.uuid,
                            properties: { ...update.properties, ...update.properties_to_set },
                        })
                        results.set(update.uuid, { success: true, version: update.version + 1 })
                    }
                }
                return Promise.resolve(results)
            }),
            // Individual NO_ASSERT write: the anon row does not exist any more.
            updatePerson: jest.fn().mockImplementation((p: InternalPerson, fields: any) => {
                if (p.uuid !== survivor.uuid) {
                    const { NoRowsUpdatedError } = require('~/common/utils/utils')
                    return Promise.reject(new NoRowsUpdatedError('gone'))
                }
                writes.push({ uuid: p.uuid, properties: fields.properties })
                return Promise.resolve([{ ...p, ...fields }, [], true])
            }),
            // ASSERT_VERSION write: no row matches the anon uuid.
            // The real statement writes properties with properties_to_set applied and
            // properties_to_unset removed, guarded by the version it read.
            updatePersonAssertVersion: jest.fn().mockImplementation((update: any) => {
                if (update.uuid !== survivor.uuid) {
                    return Promise.resolve([undefined, []])
                }
                const properties = { ...update.properties, ...update.properties_to_set }
                for (const key of update.properties_to_unset) {
                    delete properties[key]
                }
                writes.push({ uuid: update.uuid, properties })
                return Promise.resolve([update.version + 1, []])
            }),
        }
    })

    it.each(['NO_ASSERT', 'ASSERT_VERSION'] as const)(
        'keeps the $set of an event whose person creation lost the race to an attach, in %s mode',
        async (dbWriteMode) => {
            const outputs = createMockIngestionOutputs<
                PersonsOutput | PersonDistinctIdsOutput | typeof INGESTION_WARNINGS_OUTPUT | PersonMergeEventsOutput
            >()
            const store = new BatchWritingPersonsStore(repo, outputs, { dbWriteMode, useBatchUpdates: true })
            // Before this pod ever saw the anon id, an identify on another pod attached it to the survivor.
            repo.createPerson = jest.fn().mockResolvedValue({
                success: false,
                error: 'CreationConflict',
                distinctIds: [ANON],
                conflictingPerson: survivor,
            })
            const forBatch = new BatchBoundPersonsStore(store, 0)
            const context = new PersonContext(
                { uuid: 'event-1', distinct_id: ANON, properties: { $set: { seed: 'value' } } } as any,
                { id: TEAM_ID } as any,
                ANON,
                DateTime.fromISO('2026-01-01T00:00:01Z'),
                true,
                { produce: jest.fn().mockResolvedValue(undefined) } as any,
                forBatch,
                0,
                createDefaultSyncMergeMode(),
                false,
                false
            )

            const [updated] = await new PersonPropertyService(context).handleUpdate()
            expect(updated.uuid).toBe(survivor.uuid)
            expect(updated.properties).toMatchObject({ seed: 'value' })

            await store.flush()
            const survivorWrites = writes.filter((w) => w.uuid === survivor.uuid)
            expect(survivorWrites.length).toBeGreaterThan(0)
            expect(survivorWrites.at(-1)!.properties).toMatchObject({ seed: 'value', user_prop: 'kept' })
        }
    )

    it.each(['NO_ASSERT', 'ASSERT_VERSION'] as const)(
        'reapplies the update to the survivor in %s mode',
        async (dbWriteMode) => {
            const outputs = createMockIngestionOutputs<
                PersonsOutput | PersonDistinctIdsOutput | typeof INGESTION_WARNINGS_OUTPUT | PersonMergeEventsOutput
            >()
            const store = new BatchWritingPersonsStore(repo, outputs, { dbWriteMode, useBatchUpdates: true })

            // The seed event: a $set buffered on the anon person while it still exists on this pod.
            await store.applyEventOps(anon, setOps({ seed: 'value' }), ANON, 0)

            // Another writer merges the anon person into the survivor before this pod flushes.
            await store.flush()

            const survivorWrites = writes.filter((w) => w.uuid === survivor.uuid)
            expect(survivorWrites.length).toBeGreaterThan(0)
            expect(survivorWrites.at(-1)!.properties).toMatchObject({ seed: 'value', user_prop: 'kept' })
        }
    )
})
