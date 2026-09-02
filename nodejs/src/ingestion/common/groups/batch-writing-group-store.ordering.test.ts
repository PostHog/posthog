// sort-imports-ignore
import { DateTime } from 'luxon'

import { Properties } from '~/plugin-scaffold'
import { Group, GroupTypeIndex, ProjectId, TeamId } from '~/types'
import { parseJSON } from '~/common/utils/json-parse'
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

type PendingOperation = { label: string; run: () => void }

/**
 * Decides when each database call the store makes is allowed to complete. In immediate mode
 * every call completes as soon as it is made. In driven mode calls queue up and `drive` releases
 * them one at a time, in an order chosen by `pick`, so a test can force a specific interleaving
 * between workers or fuzz over many. Every call body is synchronous, so a call is atomic — the
 * same guarantee a single SQL statement gives.
 */
class Scheduler {
    private pending: PendingOperation[] = []
    private driving = false

    constructor(private pick: (labels: string[]) => number = () => 0) {}

    gate<T>(label: string, operation: () => T): Promise<T> {
        if (!this.driving) {
            try {
                return Promise.resolve(operation())
            } catch (error) {
                return Promise.reject(error)
            }
        }
        return new Promise<T>((resolve, reject) => {
            this.pending.push({
                label,
                run: () => {
                    try {
                        resolve(operation())
                    } catch (error) {
                        reject(error)
                    }
                },
            })
        })
    }

    async drive<T>(work: () => Promise<T>): Promise<T> {
        this.driving = true
        let settled = false
        const result = work().finally(() => {
            settled = true
        })
        result.catch(() => undefined)
        try {
            while (!settled) {
                await new Promise((resolve) => setImmediate(resolve))
                if (this.pending.length === 0) {
                    continue
                }
                const index = this.pick(this.pending.map((op) => op.label)) % this.pending.length
                const [operation] = this.pending.splice(index, 1)
                operation.run()
            }
        } finally {
            this.driving = false
        }
        return result
    }
}

function seededRandom(seed: number): () => number {
    let state = seed >>> 0
    return () => {
        state = (state + 0x6d2b79f5) >>> 0
        let t = state
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
}

/**
 * In-memory stand-in for the posthog_group table with the same write semantics as
 * PostgresGroupRepository: insertGroup throws RaceConditionError on a duplicate row,
 * updateGroupOptimistically is a compare-and-swap on version, and the batch statements merge
 * properties and take the earliest created_at server-side. One table is shared between several
 * stores to model several ingestion workers writing the same rows; `asRepository(worker)` labels
 * that worker's calls for the scheduler.
 */
class InMemoryGroupTable {
    private rows = new Map<string, Group>()
    optimisticConflicts = 0
    createRaces = 0

    constructor(private scheduler: Scheduler = new Scheduler()) {}

    get contentionEvents(): number {
        return this.optimisticConflicts + this.createRaces
    }

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

    asRepository(worker: string = 'db'): GroupRepository {
        const gate = <T>(operation: string, body: () => T): Promise<T> =>
            this.scheduler.gate(`${worker}:${operation}`, body)

        const repository = {
            fetchGroup: (teamId: TeamId, groupTypeIndex: GroupTypeIndex, groupKey: string) =>
                gate('fetchGroup', () => this.get(teamId, groupTypeIndex, groupKey)),
            fetchGroupsByKeys: () => Promise.resolve([]),
            insertGroup: (
                teamId: TeamId,
                groupTypeIndex: GroupTypeIndex,
                groupKey: string,
                groupProperties: Properties,
                createdAt: DateTime
            ) =>
                gate('insertGroup', () => {
                    if (this.rows.has(this.key(teamId, groupTypeIndex, groupKey))) {
                        this.createRaces += 1
                        throw new RaceConditionError('Parallel posthog_group inserts, retry')
                    }
                    return this.insert(teamId, groupTypeIndex, groupKey, groupProperties, createdAt).version
                }),
            insertGroupsBatch: (creates: GroupCreate[]) =>
                gate('insertGroupsBatch', () =>
                    creates.map((create): GroupCreateResult => {
                        const existing = this.rows.get(this.key(create.teamId, create.groupTypeIndex, create.groupKey))
                        if (existing) {
                            this.createRaces += 1
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
            ) =>
                gate('updateGroup', () => {
                    const row = this.rows.get(this.key(teamId, groupTypeIndex, groupKey))
                    if (!row) {
                        return undefined
                    }
                    row.group_properties = { ...groupProperties }
                    row.created_at = createdAt
                    row.version += 1
                    return row.version
                }),
            updateGroupsBatch: (updates: GroupPropertiesToSetUpdate[]) =>
                gate('updateGroupsBatch', () =>
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
            ) =>
                gate('updateGroupOptimistically', () => {
                    const row = this.rows.get(this.key(teamId, groupTypeIndex, groupKey))
                    if (!row || row.version !== expectedVersion) {
                        this.optimisticConflicts += 1
                        return undefined
                    }
                    row.group_properties = { ...groupProperties }
                    row.created_at = createdAt
                    row.version += 1
                    return row.version
                }),
            fetchGroupTypesByProjectIds: () => Promise.resolve({}),
            fetchGroupTypesByTeamIds: () => Promise.resolve({}),
            insertGroupType: () => Promise.resolve([null, false]),
            inTransaction: (_description: string, transaction: (tx: any) => Promise<any>) => transaction(repository),
        }
        return repository as unknown as GroupRepository
    }
}

type EmittedGroupRow = { version: number; group_properties: Properties }

function emittedRows(flushResults: Awaited<ReturnType<BatchWritingGroupStore['flush']>>): EmittedGroupRow[] {
    return flushResults.flatMap((result) =>
        result.messages.map((message) => {
            const parsed = parseJSON(message.value.toString())
            return { version: parsed.version, group_properties: parseJSON(parsed.group_properties) }
        })
    )
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
        options: Partial<BatchWritingGroupStoreOptions>,
        worker: string = 'db'
    ): BatchWritingGroupStore {
        const clickhouse = new ClickhouseGroupRepository({
            queueMessages: jest.fn().mockResolvedValue(undefined),
        } as unknown as IngestionOutputs<GroupsOutput>)
        const store = new BatchWritingGroupStore(table.asRepository(worker), clickhouse, {
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

    function seededRow(properties: Properties): Group {
        return {
            id: 1,
            team_id: teamId,
            group_type_index: groupTypeIndex,
            group_key: groupKey,
            group_properties: properties,
            created_at: t1,
            version: 1,
            properties_last_updated_at: {},
            properties_last_operation: {},
        }
    }

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
            table.seed(seededRow({ name: 'Acme' }))
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

        // Adversarial schedules. Three workers each process three $groupidentify events for the
        // same group, spread across two batches, flushing at random points, while the scheduler
        // releases their database calls in a seeded random order. Whatever the interleaving, the
        // row must end with every key, no worker may be left holding an unflushed delta, and the
        // highest-version row emitted for ClickHouse must be the final Postgres state.
        it('converges to the union of all writes under 150 fuzzed interleavings of three workers', async () => {
            const workers = ['A', 'B', 'C']
            const eventsPerWorker = 3
            const expected: Properties = {}
            for (const worker of workers) {
                for (let i = 0; i < eventsPerWorker; i++) {
                    expected[`${worker}${i}`] = `${worker}-${i}`
                }
            }

            let contendedRuns = 0
            for (let seed = 1; seed <= 150; seed++) {
                const random = seededRandom(seed)
                const scheduler = new Scheduler((labels) => Math.floor(random() * labels.length))
                const table = new InMemoryGroupTable(scheduler)
                const workerStores = workers.map((worker) => newStore(table, options, worker))
                const flushResults: Awaited<ReturnType<BatchWritingGroupStore['flush']>> = []

                try {
                    await scheduler.drive(() =>
                        Promise.all(
                            workerStores.map(async (store, w) => {
                                for (let i = 0; i < eventsPerWorker; i++) {
                                    const worker = workers[w]
                                    await store.upsertGroup(
                                        teamId,
                                        projectId,
                                        groupTypeIndex,
                                        groupKey,
                                        { [`${worker}${i}`]: `${worker}-${i}` },
                                        t2,
                                        random() < 0.5 ? 0 : 1
                                    )
                                    if (random() < 0.3) {
                                        flushResults.push(...(await store.flush()))
                                    }
                                }
                                flushResults.push(...(await store.flush()))
                                flushResults.push(...(await store.flush()))
                            })
                        )
                    )

                    const row = table.get(teamId, groupTypeIndex, groupKey)
                    expect(row?.group_properties).toEqual(expected)

                    const newest = emittedRows(flushResults).reduce((best, candidate) =>
                        candidate.version > best.version ? candidate : best
                    )
                    expect(newest.version).toBe(row?.version)
                    expect(newest.group_properties).toEqual(expected)

                    for (const store of workerStores) {
                        // Throws if a delta is still dirty, which would mean a flush lost a write.
                        await store.shutdown()
                    }
                    stores.splice(0)
                    if (table.contentionEvents > 0) {
                        contendedRuns += 1
                    }
                } catch (error) {
                    throw new Error(`seed ${seed}: ${error instanceof Error ? error.message : String(error)}`)
                }
            }
            // Convergence on uncontended schedules proves nothing. Most seeds must have made
            // workers collide on a create or a version check.
            expect(contendedRuns).toBeGreaterThan(75)
        })

        // The one thing order does decide: two writers setting the same key to different
        // values. The winner is whichever database call the scheduler releases last, and both
        // outcomes are reachable. Today these two writers are two distinct_ids on two workers,
        // so the per-distinct_id lane does not order them either.
        it.each([
            ['A', 'pro'],
            ['B', 'free'],
        ])(
            'lets the last writer win on a shared key: releasing worker %s first leaves plan=%s',
            async (first, winner) => {
                const scheduler = new Scheduler((labels) => {
                    const preferred = labels.findIndex((label) => label.startsWith(`${first}:`))
                    return preferred === -1 ? 0 : preferred
                })
                const table = new InMemoryGroupTable(scheduler)
                table.seed(seededRow({ name: 'Acme' }))
                const workerA = newStore(table, options, 'A')
                const workerB = newStore(table, options, 'B')

                await scheduler.drive(async () => {
                    await Promise.all([
                        workerA.upsertGroup(teamId, projectId, groupTypeIndex, groupKey, { plan: 'free' }, t2),
                        workerB.upsertGroup(teamId, projectId, groupTypeIndex, groupKey, { plan: 'pro' }, t2),
                    ])
                    await Promise.all([workerA.flush(), workerB.flush()])
                })

                expect(table.get(teamId, groupTypeIndex, groupKey)?.group_properties).toEqual({
                    name: 'Acme',
                    plan: winner,
                })
            }
        )
    })
})
