import { buildIntegerMatcher } from '~/common/config/config'
import { PERSON_MERGE_EVENTS_OUTPUT } from '~/common/outputs'
import { UUIDT } from '~/common/utils/utils'
import { InternalPerson } from '~/types'

import { MergeEventsConfig, PostgresPersonMerge, personMergeEventProducedCounter } from './person-merge-postgres'
import { createDefaultSyncMergeMode } from './person-merge-types'
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
            opId: eventUuid,
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

    function buildSingleSourceMerge(store: object, eventUuid: string): PostgresPersonMerge {
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
            opId: eventUuid,
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
            },
            request,
            0
        )
    }

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
