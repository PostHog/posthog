import { buildIntegerMatcher } from '~/common/config/config'
import { PERSON_DISTINCT_IDS_OUTPUT, PERSON_MERGE_EVENTS_OUTPUT } from '~/common/outputs'
import { defaultRetryConfig } from '~/common/utils/retries'
import { UUIDT } from '~/common/utils/utils'
import { InternalPerson } from '~/types'

import { MergeMappingDebounce } from './merge-mapping-debounce'
import {
    MergeEventsConfig,
    PostgresMergePolicy,
    PostgresPersonMerge,
    personMergeEventProducedCounter,
} from './person-merge-postgres'
import { MergeCreationConflictError, createDefaultSyncMergeMode } from './person-merge-types'
import { MergePersonsRequest } from './persons-store'

describe('PostgresPersonMerge merge events', () => {
    let mockOutputs: { produce: jest.Mock }

    const sourcePerson = { uuid: '01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee' } as InternalPerson
    const targetPerson = { uuid: '01928bbb-cccc-dddd-eeee-ffffffffffff' } as InternalPerson

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
                isTombstoneTeam: () => false,
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
        const tx = { addDistinctId: jest.fn().mockResolvedValue([mappingMessage]) }
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

    // $identify must never fold an already identified person into someone else. When only
    // the source exists, attaching the target id to it puts a second login on that identity.
    // The both-exist branch already refuses this.
    it('a one-exists merge refuses an already identified source', async () => {
        mockOutputs = { produce: jest.fn().mockResolvedValue(undefined) }
        const identifiedSource = {
            id: 'p1',
            uuid: sourcePerson.uuid,
            team_id: 2,
            is_identified: true,
        } as unknown as InternalPerson
        const store = {
            fetchForUpdate: jest
                .fn()
                .mockImplementation((_teamId: number, distinctId: string) =>
                    Promise.resolve(distinctId === 'anon' ? identifiedSource : null)
                ),
            inTransaction: jest.fn(),
        }
        const merge = buildSingleSourceMerge(store, new UUIDT().toString())

        const result = await merge.execute()

        expect(store.inTransaction).not.toHaveBeenCalled()
        expect(result.survivor).toBeNull()
        expect(result.results).toEqual([
            { sourceDistinctId: 'anon', outcome: 'skipped_already_identified', sourcePersonUuid: sourcePerson.uuid },
        ])
    })

    // The conflict resolves to whichever person holds one of the two ids. That can be the
    // source's holder alone, so accepting it as the survivor leaves the target id mapped to
    // no person. The merge must throw and retry against committed state.
    it('a neither-exists merge that loses the creation race throws and purges both ids', async () => {
        mockOutputs = { produce: jest.fn().mockResolvedValue(undefined) }
        const holder = { id: 'p1', uuid: sourcePerson.uuid, team_id: 2 } as unknown as InternalPerson
        const tx = {
            createPerson: jest.fn().mockResolvedValue({
                success: false,
                error: 'CreationConflict',
                distinctIds: ['d', 'anon'],
            }),
        }
        let branchFetches = 0
        const store = {
            fetchForUpdate: jest.fn().mockImplementation(() => {
                branchFetches += 1
                // The first two calls decide the branch; later ones are the conflict lookup.
                return Promise.resolve(branchFetches <= 2 ? null : holder)
            }),
            removeDistinctIdFromCache: jest.fn(),
            inTransaction: jest
                .fn()
                .mockImplementation((_description: string, body: (tx: unknown) => Promise<unknown>) => body(tx)),
        }
        const merge = buildSingleSourceMerge(store, new UUIDT().toString())

        await expect(merge.execute()).rejects.toThrow(MergeCreationConflictError)

        expect(store.removeDistinctIdFromCache).toHaveBeenCalledWith(2, 'd')
        expect(store.removeDistinctIdFromCache).toHaveBeenCalledWith(2, 'anon')
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
        const store = {
            fetchForUpdate: jest.fn().mockResolvedValue(person),
            fetchPersonDistinctIdMappings: jest.fn().mockResolvedValue([mapping]),
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
                isTombstoneTeam: () => false,
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
                isTombstoneTeam: () => false,
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

    // A bootstrap that never wins the person-creation race is contention the sequential
    // path retries around, not an unexpected fault. The fallback counter's reason label
    // is the only thing that tells the two apart.
    it('a fold bootstrap that keeps losing the creation race aborts under the conflict label', async () => {
        mockOutputs = { produce: jest.fn().mockResolvedValue(undefined) }
        const previousInterval = defaultRetryConfig.RETRY_INTERVAL_DEFAULT
        defaultRetryConfig.RETRY_INTERVAL_DEFAULT = 0
        const uuidHolder = { id: 'p1', uuid: sourcePerson.uuid, team_id: 2 } as unknown as InternalPerson
        const tx = {
            createPerson: jest.fn().mockResolvedValue({
                success: false,
                error: 'CreationConflict',
                distinctIds: ['d', 'anon-1'],
                conflictingPerson: uuidHolder,
            }),
        }
        const store = {
            fetchForUpdate: jest.fn().mockResolvedValue(null),
            removeDistinctIdFromCache: jest.fn(),
            inTransaction: jest
                .fn()
                .mockImplementation((_description: string, body: (tx: unknown) => Promise<unknown>) => body(tx)),
        }
        const eventUuid = new UUIDT().toString()
        const request: MergePersonsRequest = {
            teamId: 2,
            targetDistinctId: 'd',
            sources: [
                { distinctId: 'anon-1', eventUuid },
                { distinctId: 'anon-2', eventUuid },
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
                isTombstoneTeam: () => false,
                mergeEvents: { enabled: false, partitionCount: 64, isTeamEnabled: () => false },
            },
            request,
            0
        )

        const result = await merge.execute()
        defaultRetryConfig.RETRY_INTERVAL_DEFAULT = previousInterval

        expect(result.foldAborted).toBe('conflict')
        expect(result.survivor).toBeNull()
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
