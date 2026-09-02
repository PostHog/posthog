// sort-imports-ignore
import { DateTime } from 'luxon'

import { Properties } from '~/plugin-scaffold'
import { Group, GroupTypeIndex, ProjectId, TeamId } from '~/types'
import { RaceConditionError } from '~/common/utils/utils'

import { BatchWritingGroupStore } from './batch-writing-group-store'
import { ClickhouseGroupRepository } from '~/common/groups/repositories/clickhouse-group-repository'
import { GroupRepository } from '~/common/groups/repositories/group-repository.interface'

jest.mock('~/ingestion/common/ingestion-warnings', () => ({
    emitIngestionWarning: jest.fn().mockResolvedValue(undefined),
}))

import { GroupsOutput, IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'

/**
 * In-memory stand-in for the posthog_group table with the same concurrency semantics as
 * PostgresGroupRepository: insertGroup throws RaceConditionError on a duplicate row,
 * updateGroup bumps version unconditionally, updateGroupOptimistically is a compare-and-swap
 * on version. Each method body has no await, so every operation is atomic — the same
 * guarantee a single SQL statement gives. One table can be shared between several stores
 * to model several ingestion workers writing the same rows.
 */
class InMemoryGroupTable {
    private rows = new Map<string, Group>()
    optimisticConflicts = 0

    private key(teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string): string {
        return `${teamId}:${groupTypeIndex}:${groupKey}`
    }

    get(teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string): Group | undefined {
        const row = this.rows.get(this.key(teamId, groupTypeIndex, groupKey))
        return row ? { ...row, group_properties: { ...row.group_properties } } : undefined
    }

    seed(group: Group): void {
        this.rows.set(this.key(group.team_id, group.group_type_index, group.group_key), group)
    }

    asRepository(): GroupRepository {
        const repository = {
            fetchGroup: (teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string) =>
                Promise.resolve(this.get(teamId, groupTypeIndex, groupKey)),
            fetchGroupsByKeys: () => Promise.resolve([]),
            insertGroup: (
                teamId: TeamId,
                groupTypeIndex: GroupTypeIndex,
                groupKey: string,
                groupProperties: Properties,
                createdAt: DateTime
            ) => {
                const key = this.key(teamId, groupTypeIndex, groupKey)
                if (this.rows.has(key)) {
                    return Promise.reject(new RaceConditionError('Parallel posthog_group inserts, retry'))
                }
                this.rows.set(key, {
                    id: this.rows.size + 1,
                    team_id: teamId,
                    group_type_index: groupTypeIndex,
                    group_key: groupKey,
                    group_properties: { ...groupProperties },
                    created_at: createdAt,
                    version: 1,
                    properties_last_updated_at: {},
                    properties_last_operation: {},
                })
                return Promise.resolve(1)
            },
            updateGroup: (
                teamId: TeamId,
                groupTypeIndex: GroupTypeIndex,
                groupKey: string,
                groupProperties: Properties,
                createdAt: DateTime
            ) => {
                const row = this.rows.get(this.key(teamId, groupTypeIndex, groupKey))
                if (!row) {
                    return Promise.resolve(undefined)
                }
                row.version += 1
                row.group_properties = { ...groupProperties }
                row.created_at = createdAt
                return Promise.resolve(row.version)
            },
            updateGroupOptimistically: (
                teamId: TeamId,
                groupTypeIndex: GroupTypeIndex,
                groupKey: string,
                expectedVersion: number,
                groupProperties: Properties,
                createdAt: DateTime
            ) => {
                const row = this.rows.get(this.key(teamId, groupTypeIndex, groupKey))
                if (!row || row.version !== expectedVersion) {
                    this.optimisticConflicts += 1
                    return Promise.resolve(undefined)
                }
                row.version += 1
                row.group_properties = { ...groupProperties }
                row.created_at = createdAt
                return Promise.resolve(row.version)
            },
            fetchGroupTypesByProjectIds: () => Promise.resolve({}),
            fetchGroupTypesByTeamIds: () => Promise.resolve({}),
            insertGroupType: () => Promise.resolve([null, false]),
            inTransaction: (_description: string, transaction: (tx: any) => Promise<any>) => transaction(repository),
        }
        return repository as unknown as GroupRepository
    }
}

describe('BatchWritingGroupStore ordering', () => {
    const teamId: TeamId = 1
    const projectId = 1 as ProjectId
    const groupTypeIndex: GroupTypeIndex = 0
    const groupKey = 'acme'

    const t1 = DateTime.fromISO('2026-01-01T10:00:00.000Z', { zone: 'utc' })
    const t2 = DateTime.fromISO('2026-01-01T11:00:00.000Z', { zone: 'utc' })
    const t3 = DateTime.fromISO('2026-01-01T12:00:00.000Z', { zone: 'utc' })

    type GroupIdentify = { distinctId: string; properties: Properties; timestamp: DateTime }

    // Three users identify the same company from three distinct_ids. Because the pipeline only
    // serializes per token:distinct_id, these can be processed in any order and in parallel.
    const events: GroupIdentify[] = [
        { distinctId: 'alice', properties: { plan: 'enterprise' }, timestamp: t2 },
        { distinctId: 'bob', properties: { seats: 40 }, timestamp: t1 },
        { distinctId: 'carol', properties: { name: 'Acme' }, timestamp: t3 },
    ]

    const stores: BatchWritingGroupStore[] = []

    function newStore(table: InMemoryGroupTable): BatchWritingGroupStore {
        const clickhouse = {
            upsertGroup: jest.fn().mockResolvedValue(undefined),
        } as unknown as ClickhouseGroupRepository
        const outputs = {} as unknown as IngestionOutputs<GroupsOutput | IngestionWarningsOutput>
        const store = new BatchWritingGroupStore(outputs, table.asRepository(), clickhouse, {
            optimisticUpdateRetryInterval: 1,
            metricEmissionIntervalMs: 0,
        })
        stores.push(store)
        return store
    }

    afterEach(async () => {
        for (const store of stores.splice(0)) {
            await store.flush()
            await store.shutdown()
        }
    })

    async function processInOrder(
        ordered: GroupIdentify[],
        flushAfterEach: boolean
    ): Promise<{ row: Group | undefined; table: InMemoryGroupTable }> {
        const table = new InMemoryGroupTable()
        const store = newStore(table)
        for (const [batchId, event] of ordered.entries()) {
            await store.upsertGroup(
                teamId,
                projectId,
                groupTypeIndex,
                groupKey,
                event.properties,
                event.timestamp,
                flushAfterEach ? batchId : 0
            )
            if (flushAfterEach) {
                await store.flush()
            }
        }
        await store.flush()
        return { row: table.get(teamId, groupTypeIndex, groupKey), table }
    }

    describe.each([
        ['all in one batch', false],
        ['one batch per event', true],
    ])('%s', (_label, flushAfterEach) => {
        it('reaches the same group properties whichever order the events are processed in', async () => {
            const forward = await processInOrder(events, flushAfterEach)
            const reversed = await processInOrder([...events].reverse(), flushAfterEach)
            const rotated = await processInOrder([events[1], events[2], events[0]], flushAfterEach)

            const expected = { plan: 'enterprise', seats: 40, name: 'Acme' }
            expect(forward.row?.group_properties).toEqual(expected)
            expect(reversed.row?.group_properties).toEqual(expected)
            expect(rotated.row?.group_properties).toEqual(expected)
            expect(reversed.row?.version).toEqual(forward.row?.version)
        })

        // The store computes created_at = min(existing, event timestamp) when it creates a row
        // or takes the transactional path, but the batched merge path keeps the cached created_at
        // and never looks at the incoming timestamp (addToBatch), and the CAS-conflict refetch
        // does not min either. So created_at depends on which event happened to arrive first.
        // Marked failing to document the gap; passing it needs DateTime.min in both places.
        it.failing(
            'keeps created_at as the earliest event timestamp whichever order the events arrive in',
            async () => {
                const forward = await processInOrder(events, flushAfterEach)
                const reversed = await processInOrder([...events].reverse(), flushAfterEach)

                expect(forward.row?.created_at.toISO()).toBe(t1.toISO())
                expect(reversed.row?.created_at.toISO()).toBe(t1.toISO())
            }
        )
    })

    it('two workers flushing the same group at once converge with no lost update', async () => {
        const table = new InMemoryGroupTable()
        table.seed({
            id: 1,
            team_id: teamId,
            group_type_index: groupTypeIndex,
            group_key: groupKey,
            group_properties: { name: 'Acme' },
            created_at: t1,
            version: 1,
            properties_last_updated_at: {},
            properties_last_operation: {},
        })
        const workerA = newStore(table)
        const workerB = newStore(table)

        // Both workers read version 1 into their caches before either writes.
        await workerA.upsertGroup(teamId, projectId, groupTypeIndex, groupKey, { plan: 'enterprise' }, t2)
        await workerB.upsertGroup(teamId, projectId, groupTypeIndex, groupKey, { seats: 40 }, t2)

        await Promise.all([workerA.flush(), workerB.flush()])

        const row = table.get(teamId, groupTypeIndex, groupKey)
        expect(row?.group_properties).toEqual({ name: 'Acme', plan: 'enterprise', seats: 40 })
        expect(row?.version).toBe(3)
        // The version compare-and-swap, not arrival order, is what resolved the interleaving.
        expect(table.optimisticConflicts).toBeGreaterThan(0)
    })

    it('two workers racing to create the same group both end up in the row', async () => {
        const table = new InMemoryGroupTable()
        const workerA = newStore(table)
        const workerB = newStore(table)

        await Promise.all([
            workerA.upsertGroup(teamId, projectId, groupTypeIndex, groupKey, { plan: 'enterprise' }, t2),
            workerB.upsertGroup(teamId, projectId, groupTypeIndex, groupKey, { seats: 40 }, t1),
        ])
        await Promise.all([workerA.flush(), workerB.flush()])

        const row = table.get(teamId, groupTypeIndex, groupKey)
        expect(row?.group_properties).toEqual({ plan: 'enterprise', seats: 40 })
    })
})
