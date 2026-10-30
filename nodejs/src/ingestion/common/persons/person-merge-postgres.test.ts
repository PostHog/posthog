import { DateTime } from 'luxon'

import { buildIntegerMatcher } from '~/common/config/config'
import { PERSON_DISTINCT_IDS_OUTPUT, PERSON_MERGE_EVENTS_OUTPUT } from '~/common/outputs'
import { UUIDT } from '~/common/utils/utils'
import { InternalPerson } from '~/types'

import { MergeMappingDebounce } from './merge-mapping-debounce'
import {
    MergeEventsConfig,
    PostgresMergePolicy,
    PostgresPersonMerge,
    personMergeEventProducedCounter,
} from './person-merge-postgres'
import { MergeOutcomeOversizedError, createDefaultSyncMergeMode } from './person-merge-types'
import { MergePersonsRequest } from './persons-store'

describe('PostgresPersonMerge merge events', () => {
    let mockOutputs: { produce: jest.Mock }

    const sourcePerson = { uuid: '01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee' } as InternalPerson
    const targetPerson = { uuid: '01928bbb-cccc-dddd-eeee-ffffffffffff' } as InternalPerson

    function person(overrides: Partial<InternalPerson> = {}): InternalPerson {
        return {
            id: 'p1',
            uuid: targetPerson.uuid,
            team_id: 2,
            properties: {},
            created_at: DateTime.fromISO('2020-01-01T00:00:00.000Z', { zone: 'utc' }),
            version: 0,
            is_identified: false,
            is_user_id: null,
            properties_last_updated_at: {},
            properties_last_operation: {},
            last_seen_at: null,
            ...overrides,
        }
    }

    function buildMerge(teamId: number, mergeEvents: MergeEventsConfig): PostgresPersonMerge {
        mockOutputs = { produce: jest.fn().mockResolvedValue(undefined) }
        const eventUuid = new UUIDT().toString()
        const request: MergePersonsRequest = {
            teamId,
            targetDistinctId: 'd',
            sources: [{ distinctId: 'anon', eventUuid }],
            eventOps: {
                set: {},
                setOnce: {},
                unset: [],
                denied: false,
                shouldForceUpdate: true,
                eventName: '$identify',
            },
            eventUuid: eventUuid,
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        }
        return new PostgresPersonMerge(
            {} as any,
            mockOutputs as any,
            {
                updateAllProperties: false,
                isLockedOutcomeTeam: () => true,
                mergeEvents,
            },
            request,
            0
        )
    }

    function produceMergeEvent(merge: PostgresPersonMerge): Promise<void> {
        return (merge as any).producePersonMergeEvent(sourcePerson, targetPerson)
    }

    // The producer must never emit for teams outside the allowlist (the whole point of the gate):
    // a regression that widened it would flood the cohort-stream-processor with out-of-scope events.
    it.each([
        {
            name: 'disabled: no-op even for an allowlisted team',
            enabled: false,
            allowlist: '2',
            teamId: 2,
            produces: false,
        },
        {
            name: 'enabled + team in the default allowlist produces',
            enabled: true,
            allowlist: '2',
            teamId: 2,
            produces: true,
        },
        {
            name: 'enabled + team outside the allowlist is a no-op',
            enabled: true,
            allowlist: '2',
            teamId: 99,
            produces: false,
        },
        {
            name: 'enabled + wildcard allowlist produces for any team',
            enabled: true,
            allowlist: '*',
            teamId: 99,
            produces: true,
        },
        {
            // Node treats an empty allowlist as match-nothing, the opposite of Rust's "empty means all".
            // Clearing the env var expecting the Rust behavior silently stops all emission.
            name: 'enabled + empty allowlist is a no-op (empty matches no teams)',
            enabled: true,
            allowlist: '',
            teamId: 2,
            produces: false,
        },
    ])('producePersonMergeEvent $name', async ({ enabled, allowlist, teamId, produces }) => {
        const merge = buildMerge(teamId, {
            enabled,
            partitionCount: 64,
            isTeamEnabled: buildIntegerMatcher(allowlist, true),
        })

        await produceMergeEvent(merge)

        if (produces) {
            expect(mockOutputs.produce).toHaveBeenCalledTimes(1)
            expect(mockOutputs.produce).toHaveBeenCalledWith(
                PERSON_MERGE_EVENTS_OUTPUT,
                expect.objectContaining({ teamId })
            )
        } else {
            expect(mockOutputs.produce).not.toHaveBeenCalled()
        }
    })

    // Merge verbs update the batch caches optimistically inside transactions;
    // a failure after that leaves mappings that were never committed, and the
    // caller's retry would read them back as truth.
    it('a failed single-source merge purges both distinct ids before rethrowing', async () => {
        mockOutputs = { produce: jest.fn().mockResolvedValue(undefined) }
        const store = {
            fetchForUpdate: jest.fn().mockRejectedValue(new Error('connection lost')),
            removeDistinctIdFromCache: jest.fn(),
        }
        const eventUuid = new UUIDT().toString()
        const merge = buildSingleSourceMerge(store, eventUuid)

        await expect(merge.execute()).rejects.toThrow('connection lost')

        expect(store.removeDistinctIdFromCache).toHaveBeenCalledWith(2, 'd')
        expect(store.removeDistinctIdFromCache).toHaveBeenCalledWith(2, 'anon')
    })

    // A produce awaited inside the merge transaction holds row locks and lifecycle
    // marks across the Kafka roundtrip, and its ack escapes the batch-end await.
    it('a one-exists merge produces the mapping after the transaction and surfaces the ack', async () => {
        const order: string[] = []
        mockOutputs = {
            produce: jest.fn().mockImplementation(() => {
                order.push('produce')
                return Promise.resolve()
            }),
        }
        const existingPerson = { id: 'p1', uuid: targetPerson.uuid, team_id: 2 } as unknown as InternalPerson
        const mappingMessage = {
            output: PERSON_DISTINCT_IDS_OUTPUT,
            value: Buffer.from('{}'),
        }
        const tx = {
            claimLifecycleMarks: jest.fn(),
            isPersonLive: jest.fn().mockResolvedValue(true),
            readMergeRows: jest.fn().mockResolvedValue([existingPerson]),
            addDistinctId: jest.fn().mockResolvedValue([mappingMessage]),
            updatePersonForMerge: jest.fn().mockResolvedValue([existingPerson, [], false]),
            releaseLifecycleMarks: jest.fn(),
        }
        const store = {
            fetchForUpdate: jest
                .fn()
                .mockImplementation((_teamId: number, distinctId: string) =>
                    Promise.resolve(distinctId === 'd' ? existingPerson : null)
                ),
            inTransaction: jest
                .fn()
                .mockImplementation(async (_description: string, body: (tx: unknown) => Promise<unknown>) => {
                    const result = await body(tx)
                    order.push('commit')
                    return result
                }),
        }
        const merge = buildSingleSourceMerge(store, new UUIDT().toString())

        const result = await merge.execute()

        expect(order).toEqual(['commit', 'produce'])
        expect(mockOutputs.produce).toHaveBeenCalledWith(
            PERSON_DISTINCT_IDS_OUTPUT,
            expect.objectContaining({ teamId: 2, value: mappingMessage.value })
        )
        expect(result.results).toEqual([{ sourceDistinctId: 'anon', outcome: 'attached' }])
        await expect(result.kafkaAck).resolves.toBeUndefined()
    })

    // The identified flag must commit with the mapping so another pod cannot attach a second user, and the
    // committed row decides it: the batch's view can already show the flag pending.
    it.each([
        { name: 'writes the flag from the committed row and caches it', locked: true, cached: false, row: false },
        { name: 'writes the flag when only the batch view shows it pending', locked: true, cached: true, row: false },
        { name: 'leaves the row and cache alone when the row is identified', locked: true, cached: false, row: true },
        { name: 'defers the flag to the flush for a deferred-outcome team', locked: false, cached: false, row: false },
    ])('a one-exists merge $name', async ({ locked, cached, row }) => {
        const order: string[] = []
        const existingPerson = {
            id: 'p1',
            uuid: targetPerson.uuid,
            team_id: 2,
            is_identified: cached,
        } as unknown as InternalPerson
        const committedRow = { ...existingPerson, is_identified: row, version: 1 } as InternalPerson
        const writtenRow = { ...committedRow, is_identified: true, version: 2 } as InternalPerson
        const cachedRow = { ...writtenRow, properties: { pending: true } } as InternalPerson
        const flagMessage = { output: PERSON_DISTINCT_IDS_OUTPUT, value: Buffer.from('{"flag":true}') }
        const tx = {
            claimLifecycleMarks: jest.fn(),
            isPersonLive: jest.fn().mockResolvedValue(true),
            readMergeRows: jest.fn().mockImplementation(() => {
                order.push('readMergeRows')
                return Promise.resolve([committedRow])
            }),
            addDistinctId: jest.fn().mockImplementation(() => {
                order.push('addDistinctId')
                return Promise.resolve([])
            }),
            updatePersonForMerge: jest.fn().mockImplementation(() => {
                order.push('updatePersonForMerge')
                return Promise.resolve([writtenRow, [flagMessage], true])
            }),
            releaseLifecycleMarks: jest.fn().mockImplementation(() => {
                order.push('releaseLifecycleMarks')
                return Promise.resolve()
            }),
        }
        const store = {
            fetchForUpdate: jest
                .fn()
                .mockImplementation((_teamId: number, distinctId: string) =>
                    Promise.resolve(distinctId === 'd' ? existingPerson : null)
                ),
            inTransaction: jest
                .fn()
                .mockImplementation(async (_description: string, body: (tx: unknown) => Promise<unknown>) => {
                    const result = await body(tx)
                    order.push('commit')
                    return result
                }),
            takeMergedRow: jest.fn().mockImplementation(() => {
                order.push('takeMergedRow')
                return cachedRow
            }),
        }
        const merge = buildSingleSourceMerge(store, new UUIDT().toString(), { isLockedOutcomeTeam: () => locked })

        const result = await merge.execute()

        expect(result.results).toEqual([{ sourceDistinctId: 'anon', outcome: 'attached' }])
        if (locked && !row) {
            expect(order).toEqual([
                'readMergeRows',
                'addDistinctId',
                'updatePersonForMerge',
                'releaseLifecycleMarks',
                'commit',
                'takeMergedRow',
            ])
            expect(tx.updatePersonForMerge).toHaveBeenCalledWith(committedRow, { is_identified: true }, 'd')
            expect(store.takeMergedRow).toHaveBeenCalledWith(writtenRow, 'd', { is_identified: true }, null, 0)
            expect(mockOutputs.produce).toHaveBeenCalledWith(
                PERSON_DISTINCT_IDS_OUTPUT,
                expect.objectContaining({ value: flagMessage.value })
            )
            expect(result.survivor).toBe(cachedRow)
        } else {
            expect(tx.readMergeRows).toHaveBeenCalledTimes(locked ? 1 : 0)
            expect(tx.updatePersonForMerge).not.toHaveBeenCalled()
            expect(store.takeMergedRow).not.toHaveBeenCalled()
            expect(result.survivor).toBe(existingPerson)
        }
    })

    it('a one-exists merge on a row over the size limit commits the mapping without the flag', async () => {
        const existingPerson = { id: 'p1', uuid: targetPerson.uuid, team_id: 2 } as unknown as InternalPerson
        const mappingMessage = { output: PERSON_DISTINCT_IDS_OUTPUT, value: Buffer.from('{}') }
        const tx = {
            claimLifecycleMarks: jest.fn(),
            isPersonLive: jest.fn().mockResolvedValue(true),
            readMergeRows: jest.fn().mockResolvedValue([existingPerson]),
            addDistinctId: jest.fn().mockResolvedValue([mappingMessage]),
            updatePersonForMerge: jest.fn().mockRejectedValue(new MergeOutcomeOversizedError('over the limit')),
            releaseLifecycleMarks: jest.fn(),
        }
        const store = {
            fetchForUpdate: jest
                .fn()
                .mockImplementation((_teamId: number, distinctId: string) =>
                    Promise.resolve(distinctId === 'd' ? existingPerson : null)
                ),
            inTransaction: jest
                .fn()
                .mockImplementation((_description: string, body: (tx: unknown) => Promise<unknown>) => body(tx)),
            takeMergedRow: jest.fn(),
        }
        const merge = buildSingleSourceMerge(store, new UUIDT().toString())

        const result = await merge.execute()

        expect(store.inTransaction).toHaveBeenCalledTimes(2)
        expect(tx.updatePersonForMerge).toHaveBeenCalledTimes(1)
        expect(tx.addDistinctId).toHaveBeenCalledTimes(2)
        expect(store.takeMergedRow).not.toHaveBeenCalled()
        expect(mockOutputs.produce).toHaveBeenCalledTimes(1)
        expect(result.results).toEqual([{ sourceDistinctId: 'anon', outcome: 'attached' }])
        expect(result.survivor).toBe(existingPerson)
    })

    // The outcomes that leave the target row untouched follow the one-exists rule: the committed row decides,
    // and the flag commits at the call rather than riding the flush where another pod would read it late.
    it.each([
        { outcome: 'noop_same_person', locked: true, row: false, writes: true },
        { outcome: 'noop_same_person', locked: true, row: true, writes: false },
        { outcome: 'noop_same_person', locked: false, row: false, writes: false },
        { outcome: 'skipped_already_identified', locked: true, row: false, writes: true },
        { outcome: 'skipped_already_identified', locked: true, row: true, writes: false },
        { outcome: 'skipped_already_identified', locked: false, row: false, writes: false },
    ])(
        'a $outcome identify (locked $locked, row identified $row) writes the flag at the call: $writes',
        async ({ outcome, locked, row, writes }) => {
            const order: string[] = []
            mockOutputs = { produce: jest.fn().mockResolvedValue(undefined) }
            const target = person()
            const source =
                outcome === 'noop_same_person'
                    ? target
                    : person({ id: 'p0', uuid: sourcePerson.uuid, is_identified: true })
            const committedRow = person({ is_identified: row, version: 1 })
            const writtenRow = person({ is_identified: true, version: 2 })
            const cachedRow = person({ is_identified: true, version: 2, properties: { pending: true } })
            const flagMessage = { output: PERSON_DISTINCT_IDS_OUTPUT, value: Buffer.from('{"flag":true}') }
            const tx = {
                readMergeRows: jest.fn().mockImplementation(() => {
                    order.push('readMergeRows')
                    return Promise.resolve([committedRow])
                }),
                updatePersonForMerge: jest.fn().mockImplementation(() => {
                    order.push('updatePersonForMerge')
                    return Promise.resolve([writtenRow, [flagMessage], true])
                }),
            }
            const store = {
                fetchForUpdate: jest
                    .fn()
                    .mockImplementation((_teamId: number, distinctId: string) =>
                        Promise.resolve(distinctId === 'd' ? target : source)
                    ),
                inTransaction: jest
                    .fn()
                    .mockImplementation(async (_description: string, body: (tx: unknown) => Promise<unknown>) => {
                        const result = await body(tx)
                        order.push('commit')
                        return result
                    }),
                takeMergedRow: jest.fn().mockImplementation(() => {
                    order.push('takeMergedRow')
                    return cachedRow
                }),
            }
            const merge = buildSingleSourceMerge(store, new UUIDT().toString(), {
                isLockedOutcomeTeam: () => locked,
            })

            const result = await merge.execute()

            expect(result.results).toEqual([{ sourceDistinctId: 'anon', outcome, sourcePersonUuid: source.uuid }])
            if (writes) {
                expect(order).toEqual(['readMergeRows', 'updatePersonForMerge', 'commit', 'takeMergedRow'])
                expect(tx.updatePersonForMerge).toHaveBeenCalledWith(committedRow, { is_identified: true }, 'd')
                expect(store.takeMergedRow).toHaveBeenCalledWith(writtenRow, 'd', { is_identified: true }, null, 0)
                expect(mockOutputs.produce).toHaveBeenCalledWith(
                    PERSON_DISTINCT_IDS_OUTPUT,
                    expect.objectContaining({ value: flagMessage.value })
                )
                expect(result.survivor).toBe(cachedRow)
            } else {
                expect(tx.readMergeRows).toHaveBeenCalledTimes(locked ? 1 : 0)
                expect(tx.updatePersonForMerge).not.toHaveBeenCalled()
                expect(store.takeMergedRow).not.toHaveBeenCalled()
                expect(result.survivor).toBe(target)
            }
            await expect(result.kafkaAck).resolves.toBeUndefined()
        }
    )

    it('a same-person identify on a row over the size limit leaves the flag to the flush', async () => {
        mockOutputs = { produce: jest.fn().mockResolvedValue(undefined) }
        const target = person()
        const tx = {
            readMergeRows: jest.fn().mockResolvedValue([target]),
            updatePersonForMerge: jest.fn().mockRejectedValue(new MergeOutcomeOversizedError('over the limit')),
        }
        const store = {
            fetchForUpdate: jest.fn().mockResolvedValue(target),
            inTransaction: jest
                .fn()
                .mockImplementation((_description: string, body: (tx: unknown) => Promise<unknown>) => body(tx)),
            takeMergedRow: jest.fn(),
        }
        const merge = buildSingleSourceMerge(store, new UUIDT().toString())

        const result = await merge.execute()

        expect(tx.updatePersonForMerge).toHaveBeenCalledTimes(1)
        expect(store.takeMergedRow).not.toHaveBeenCalled()
        expect(mockOutputs.produce).not.toHaveBeenCalled()
        expect(result.results).toEqual([
            { sourceDistinctId: 'anon', outcome: 'noop_same_person', sourcePersonUuid: target.uuid },
        ])
        expect(result.survivor).toBe(target)
    })

    // Same contract as the one-exists case: createPerson returns its messages and the
    // branch produces after commit, so the creation transaction never spans Kafka.
    it('a neither-exists merge produces the creation messages after the transaction', async () => {
        const order: string[] = []
        mockOutputs = {
            produce: jest.fn().mockImplementation(() => {
                order.push('produce')
                return Promise.resolve()
            }),
        }
        const createdPerson = { id: 'p1', uuid: targetPerson.uuid, team_id: 2, is_identified: true } as InternalPerson
        const creationMessage = {
            output: PERSON_DISTINCT_IDS_OUTPUT,
            value: Buffer.from('{}'),
        }
        const tx = {
            createPerson: jest.fn().mockResolvedValue({
                success: true,
                person: createdPerson,
                created: true,
                messages: [creationMessage],
            }),
        }
        const store = {
            fetchForUpdate: jest.fn().mockResolvedValue(null),
            inTransaction: jest
                .fn()
                .mockImplementation(async (_description: string, body: (tx: unknown) => Promise<unknown>) => {
                    const result = await body(tx)
                    order.push('commit')
                    return result
                }),
        }
        const merge = buildSingleSourceMerge(store, new UUIDT().toString())

        const result = await merge.execute()

        expect(order).toEqual(['commit', 'produce'])
        expect(mockOutputs.produce).toHaveBeenCalledWith(
            PERSON_DISTINCT_IDS_OUTPUT,
            expect.objectContaining({ teamId: 2, value: creationMessage.value })
        )
        expect(result.results).toEqual([{ sourceDistinctId: 'anon', outcome: 'attached' }])
        await expect(result.kafkaAck).resolves.toBeUndefined()
    })

    // Both directions matter: never emitting loses the healing, and emitting on every
    // duplicate $identify floods the topic and keeps the overrides table from converging.
    it('an already-satisfied merge re-emits the committed mappings once per debounce window', async () => {
        mockOutputs = { produce: jest.fn().mockResolvedValue(undefined) }
        const person = { id: 'p1', uuid: targetPerson.uuid, team_id: 2 } as unknown as InternalPerson
        const mapping = {
            distinctId: 'anon',
            message: { output: PERSON_DISTINCT_IDS_OUTPUT, value: Buffer.from('{"version":1}') },
        }
        const tx = { readMergeRows: jest.fn().mockResolvedValue([{ ...person, is_identified: true }]) }
        const store = {
            fetchForUpdate: jest.fn().mockResolvedValue(person),
            fetchPersonDistinctIdMappings: jest.fn().mockResolvedValue([mapping]),
            inTransaction: jest
                .fn()
                .mockImplementation((_description: string, body: (tx: unknown) => Promise<unknown>) => body(tx)),
        }
        const debounce = new MergeMappingDebounce(100, 60_000)

        const cold = await buildSingleSourceMerge(store, new UUIDT().toString(), {
            noopMappingDebounce: debounce,
        }).execute()
        await cold.kafkaAck

        expect(cold.results[0].outcome).toBe('noop_same_person')
        expect(store.fetchPersonDistinctIdMappings).toHaveBeenCalledWith(2, ['anon', 'd'])
        expect(mockOutputs.produce).toHaveBeenCalledTimes(1)
        expect(mockOutputs.produce).toHaveBeenCalledWith(
            PERSON_DISTINCT_IDS_OUTPUT,
            expect.objectContaining({ teamId: 2, value: mapping.message.value })
        )

        const warm = await buildSingleSourceMerge(store, new UUIDT().toString(), {
            noopMappingDebounce: debounce,
        }).execute()
        await warm.kafkaAck

        expect(store.fetchPersonDistinctIdMappings).toHaveBeenCalledTimes(1)
        expect(mockOutputs.produce).toHaveBeenCalledTimes(1)
    })

    it('a replayed refusal of an identified source re-emits the target mapping its first attempt committed', async () => {
        mockOutputs = { produce: jest.fn().mockResolvedValue(undefined) }
        const target = { id: 'p-target', uuid: targetPerson.uuid, team_id: 2 } as unknown as InternalPerson
        const source = { id: 'p-source', uuid: sourcePerson.uuid, team_id: 2, is_identified: true } as InternalPerson
        const mapping = {
            distinctId: 'd',
            message: { output: PERSON_DISTINCT_IDS_OUTPUT, value: Buffer.from('{"version":0}') },
        }
        const tx = { readMergeRows: jest.fn().mockResolvedValue([{ ...target, is_identified: true }]) }
        const store = {
            fetchForUpdate: jest
                .fn()
                .mockImplementation((_teamId: number, distinctId: string) =>
                    Promise.resolve(distinctId === 'd' ? target : source)
                ),
            fetchPersonDistinctIdMappings: jest.fn().mockResolvedValue([mapping]),
            inTransaction: jest
                .fn()
                .mockImplementation((_description: string, body: (tx: unknown) => Promise<unknown>) => body(tx)),
        }

        const replay = await buildSingleSourceMerge(store, new UUIDT().toString(), {
            noopMappingDebounce: new MergeMappingDebounce(100, 60_000),
        }).execute()
        await replay.kafkaAck

        expect(replay.results[0].outcome).toBe('skipped_already_identified')
        expect(mockOutputs.produce).toHaveBeenCalledWith(
            PERSON_DISTINCT_IDS_OUTPUT,
            expect.objectContaining({ teamId: 2, value: mapping.message.value })
        )
    })

    function buildSingleSourceMerge(
        store: object,
        eventUuid: string,
        policyOverrides: Partial<PostgresMergePolicy> = {}
    ): PostgresPersonMerge {
        const request: MergePersonsRequest = {
            teamId: 2,
            targetDistinctId: 'd',
            sources: [{ distinctId: 'anon', eventUuid }],
            eventOps: {
                set: {},
                setOnce: {},
                unset: [],
                denied: false,
                shouldForceUpdate: true,
                eventName: '$identify',
            },
            eventUuid: eventUuid,
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        }
        return new PostgresPersonMerge(
            store as never,
            mockOutputs as never,
            {
                updateAllProperties: false,
                isLockedOutcomeTeam: () => true,
                mergeEvents: { enabled: false, partitionCount: 64, isTeamEnabled: () => false },
                ...policyOverrides,
            },
            request,
            0
        )
    }

    // The executor refuses the ids Postgres cannot store even when a caller
    // skips the service's pre-filter. A regression to the narrower illegal
    // list would classify these as missing sources, carry them into the fold
    // transaction, and abort the whole fold on the doomed insert.
    it('a fold refuses unstorable source ids without opening a transaction', async () => {
        mockOutputs = { produce: jest.fn().mockResolvedValue(undefined) }
        const target = { id: 't1', uuid: targetPerson.uuid } as InternalPerson
        const store = {
            fetchForUpdate: jest.fn().mockResolvedValue(target),
            fetchPersonsForUpdateByDistinctIds: jest.fn().mockResolvedValue([]),
        }
        const eventUuid = new UUIDT().toString()
        const nulId = 'anon\u0000one'
        const oversizedId = 'x'.repeat(401)
        const request: MergePersonsRequest = {
            teamId: 2,
            targetDistinctId: 'd',
            sources: [
                { distinctId: nulId, eventUuid },
                { distinctId: oversizedId, eventUuid },
            ],
            eventOps: {
                set: {},
                setOnce: {},
                unset: [],
                denied: false,
                shouldForceUpdate: true,
                eventName: '$identify',
            },
            eventUuid,
            allowIdentifiedSources: false,
            mergeMode: createDefaultSyncMergeMode(),
            createdAtMs: 3_600_000,
        }
        const merge = new PostgresPersonMerge(
            store as never,
            mockOutputs as never,
            {
                updateAllProperties: false,
                isLockedOutcomeTeam: () => true,
                mergeEvents: { enabled: false, partitionCount: 64, isTeamEnabled: () => false },
            },
            request,
            0
        )

        const result = await merge.execute()

        expect(result.foldAborted).toBeUndefined()
        expect(result.survivor).toBe(target)
        expect(result.results).toEqual([
            { sourceDistinctId: nulId, outcome: 'skipped_illegal' },
            { sourceDistinctId: oversizedId, outcome: 'skipped_illegal' },
        ])
    })

    // The produce is detached from ingestion, so a broker failure must never surface to the caller
    // and must not be counted as a delivered produce (the counter tracks broker acks, not attempts).
    it('producePersonMergeEvent swallows a produce failure without counting it', async () => {
        const merge = buildMerge(2, {
            enabled: true,
            partitionCount: 64,
            isTeamEnabled: buildIntegerMatcher('2', true),
        })
        mockOutputs.produce.mockRejectedValue(new Error('broker down'))
        const producedBefore = (await personMergeEventProducedCounter.get()).values[0]?.value ?? 0

        await expect(produceMergeEvent(merge)).resolves.toBeUndefined()

        expect(mockOutputs.produce).toHaveBeenCalledTimes(1)
        const producedAfter = (await personMergeEventProducedCounter.get()).values[0]?.value ?? 0
        expect(producedAfter).toBe(producedBefore)
    })
})
