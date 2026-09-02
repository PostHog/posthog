// sort-imports-ignore
import { DateTime } from 'luxon'

import { Properties } from '~/plugin-scaffold'
import { Group, GroupTypeIndex, ProjectId, TeamId } from '~/types'
import { RaceConditionError } from '~/common/utils/utils'

import { BatchWritingGroupStore, BatchWritingGroupStoreOptions } from './batch-writing-group-store'
import { ClickhouseGroupRepository } from '~/common/groups/repositories/clickhouse-group-repository'
import {
    GroupCreate,
    GroupCreateResult,
    GroupPropertiesToSetUpdate,
    GroupRepository,
} from '~/common/groups/repositories/group-repository.interface'
import { GroupsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'

/**
 * In-memory stand-in for the posthog_group table with the same write semantics as
 * PostgresGroupRepository: insertGroup throws RaceConditionError on a duplicate row,
 * updateGroupOptimistically is a compare-and-swap on version, and the batch statements
 * merge properties and take the earliest created_at server-side. Each method body has no
 * await, so every operation is atomic — the same guarantee a single SQL statement gives.
 * One table can be shared between several stores to model several ingestion workers
 * writing the same rows.
 */
class InMemoryGroupTable {
    private rows = new Map<string, Group>()
    optimisticConflicts = 0

    private key(teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string): string {
        return `${teamId}:${groupTypeIndex}:${groupKey}`
    }

    private clone(row: Group): Group {
        return { ...row, group_properties: { ...row.group_properties } }
    }

    get(teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string): Group | undefined {
        const row = this.rows.get(this.key(teamId, groupTypeIndex, groupKey))
        return row ? this.clone(row) : undefined
    }

    seed(group: Group): void {
        this.rows.set(this.key(group.team_id, group.group_type_index, group.group_key), group)
    }

    private insert(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        groupProperties: Properties,
        createdAt: DateTime
    ): Group {
        const row: Group = {
            id: this.rows.size + 1,
            team_id: teamId,
            group_type_index: groupTypeIndex,
            group_key: groupKey,
            group_properties: { ...groupProperties },
            created_at: createdAt,
            version: 1,
            properties_last_updated_at: {},
            properties_last_operation: {},
        }
        this.rows.set(this.key(teamId, groupTypeIndex, groupKey), row)
        return row
    }

    private merge(row: Group, propertiesToSet: Properties, createdAt: DateTime): Group {
        row.group_properties = { ...row.group_properties, ...propertiesToSet }
        row.created_at = DateTime.min(row.created_at, createdAt)
        row.version += 1
        return row
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
                if (this.rows.has(this.key(teamId, groupTypeIndex, groupKey))) {
                    return Promise.reject(new RaceConditionError('Parallel posthog_group inserts, retry'))
                }
                return Promise.resolve(
                    this.insert(teamId, groupTypeIndex, groupKey, groupProperties, createdAt).version
                )
            },
            insertGroupsBatch: (creates: GroupCreate[]) =>
                Promise.resolve(
                    creates.map((create): GroupCreateResult => {
                        const existing = this.rows.get(this.key(create.teamId, create.groupTypeIndex, create.groupKey))
                        if (existing) {
                            return {
                                ...this.clone(this.merge(existing, create.groupProperties, create.createdAt)),
                                inserted: false,
                            }
                        }
                        const row = this.insert(
                            create.teamId,
                            create.groupTypeIndex,
                            create.groupKey,
                            create.groupProperties,
                            create.createdAt
                        )
                        return { ...this.clone(row), inserted: true }
                    })
                ),
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
                row.group_properties = { ...groupProperties }
                row.created_at = createdAt
                row.version += 1
                return Promise.resolve(row.version)
            },
            updateGroupsBatch: (updates: GroupPropertiesToSetUpdate[]) =>
                Promise.resolve(
                    updates.flatMap((update) => {
                        const row = this.rows.get(this.key(update.teamId, update.groupTypeIndex, update.groupKey))
                        return row ? [this.clone(this.merge(row, update.propertiesToSet, update.createdAt))] : []
                    })
                ),
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
                row.group_properties = { ...groupProperties }
                row.created_at = createdAt
                row.version += 1
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

    type GroupIdentify = { properties: Properties; timestamp: DateTime }

    // Three users identify the same company from three distinct_ids. The pipeline only
    // serializes per token:distinct_id, so these can be processed in any order and in parallel.
    const events: GroupIdentify[] = [
        { properties: { plan: 'enterprise' }, timestamp: t2 },
        { properties: { seats: 40 }, timestamp: t1 },
        { properties: { name: 'Acme' }, timestamp: t3 },
    ]
    const mergedProperties = { plan: 'enterprise', seats: 40, name: 'Acme' }

    const stores: BatchWritingGroupStore[] = []

    function newStore(
        table: InMemoryGroupTable,
        options: Partial<BatchWritingGroupStoreOptions>
    ): BatchWritingGroupStore {
        const clickhouse = new ClickhouseGroupRepository({
            queueMessages: jest.fn().mockResolvedValue(undefined),
        } as unknown as IngestionOutputs<GroupsOutput>)
        const store = new BatchWritingGroupStore(table.asRepository(), clickhouse, {
            optimisticUpdateRetryInterval: 1,
            metricEmissionIntervalMs: 0,
            ...options,
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
        options: Partial<BatchWritingGroupStoreOptions>,
        flushAfterEach: boolean
    ): Promise<Group | undefined> {
        const table = new InMemoryGroupTable()
        const store = newStore(table, options)
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
        return table.get(teamId, groupTypeIndex, groupKey)
    }

    // Every write path the store can take: server-side merge (default), per-row version CAS,
    // and deferred batched creates.
    describe.each<[string, Partial<BatchWritingGroupStoreOptions>]>([
        ['batched merge updates', { useBatchUpdates: true }],
        ['individual CAS updates', { useBatchUpdates: false }],
        ['batched creates', { useBatchCreates: true }],
    ])('%s', (_label, options) => {
        it.each([
            ['all in one batch', false],
            ['one batch per event', true],
        ])(
            'reaches the same group properties whichever order the events are processed in, %s',
            async (_l, flushAfterEach) => {
                const forward = await processInOrder(events, options, flushAfterEach)
                const reversed = await processInOrder([...events].reverse(), options, flushAfterEach)
                const rotated = await processInOrder([events[1], events[2], events[0]], options, flushAfterEach)

                expect(forward?.group_properties).toEqual(mergedProperties)
                expect(reversed?.group_properties).toEqual(mergedProperties)
                expect(rotated?.group_properties).toEqual(mergedProperties)
                expect(reversed?.version).toEqual(forward?.version)
            }
        )

        // Only row creation takes min(now, event timestamp). When the group is already cached,
        // addToBatch keeps the cached created_at and never looks at the incoming timestamp, so
        // the LEAST() in the batch statements never sees an earlier event. The row ends up with
        // whichever event happened to create it. Marked failing to document the gap.
        it.failing(
            'keeps created_at as the earliest event timestamp whichever order the events arrive in',
            async () => {
                const forward = await processInOrder(events, options, false)
                const reversed = await processInOrder([...events].reverse(), options, false)

                expect(forward?.created_at.toISO()).toBe(t1.toISO())
                expect(reversed?.created_at.toISO()).toBe(t1.toISO())
            }
        )

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
            const workerA = newStore(table, options)
            const workerB = newStore(table, options)

            // Both workers read version 1 into their caches before either writes.
            await workerA.upsertGroup(teamId, projectId, groupTypeIndex, groupKey, { plan: 'enterprise' }, t2)
            await workerB.upsertGroup(teamId, projectId, groupTypeIndex, groupKey, { seats: 40 }, t2)

            await Promise.all([workerA.flush(), workerB.flush()])

            const row = table.get(teamId, groupTypeIndex, groupKey)
            expect(row?.group_properties).toEqual(mergedProperties)
            expect(row?.version).toBe(3)
            if (options.useBatchUpdates === false) {
                // On this path the version compare-and-swap, not arrival order, resolved the interleaving.
                expect(table.optimisticConflicts).toBeGreaterThan(0)
            }
        })

        it('two workers racing to create the same group both end up in the row', async () => {
            const table = new InMemoryGroupTable()
            const workerA = newStore(table, options)
            const workerB = newStore(table, options)

            await Promise.all([
                workerA.upsertGroup(teamId, projectId, groupTypeIndex, groupKey, { plan: 'enterprise' }, t2),
                workerB.upsertGroup(teamId, projectId, groupTypeIndex, groupKey, { seats: 40 }, t1),
            ])
            await Promise.all([workerA.flush(), workerB.flush()])

            const row = table.get(teamId, groupTypeIndex, groupKey)
            expect(row?.group_properties).toEqual({ plan: 'enterprise', seats: 40 })
        })
    })
})
