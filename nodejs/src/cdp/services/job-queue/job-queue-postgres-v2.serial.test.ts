import { DateTime } from 'luxon'
import { AddressInfo, Socket, connect, createServer } from 'node:net'
import { Pool, PoolClient } from 'pg'
import { register } from 'prom-client'
import { v4 as uuidv4, v7 as uuidv7 } from 'uuid'

import * as posthogUtils from '~/common/utils/posthog'
import { PubSub } from '~/common/utils/pubsub'
import { waitForExpect } from '~/tests/helpers/expectations'

import { createHogFunction, createIntegration } from '../../_tests/fixtures'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'
import { EncryptedFields } from '../../utils/encryption-utils'
import { markServerResolvedIntegration } from '../../utils/integration-input-refs'
import { HogInputsService } from '../hog-inputs.service'
import { IntegrationManagerService } from '../managers/integration-manager.service'
import { IntegrationSource } from '../managers/integration-source'
import { CONSUMER_STOP_DEADLINE_MS, CyclotronJobQueuePostgresV2 } from './job-queue-postgres-v2'

describe('CyclotronJobQueuePostgresV2 on Cyclotron Postgres', () => {
    const ENCRYPTION_SALT_KEYS = '00beef0000beef0000beef0000beef00'
    const baseInvocation = {
        teamId: 1,
        functionId: '0196a6b9-1104-0000-f099-9cf11985a307',
        queue: 'hog' as const,
        queuePriority: 0,
        state: {
            globals: {},
            timings: [],
            vmState: { bytecodes: {}, stack: [], upvalues: [] },
        },
    }

    function createResult(overrides: Partial<CyclotronJobInvocationResult>): CyclotronJobInvocationResult {
        return {
            invocation: { ...baseInvocation, id: uuidv4() },
            finished: false,
            error: null,
            logs: [],
            metrics: [],
            capturedPostHogEvents: [],
            warehouseWebhookPayloads: [],
            messageAssets: [],
            conversionWatchers: [],
            ...overrides,
        }
    }

    const CYCLOTRON_DB = { host: 'localhost', port: 5432, database: 'test_cyclotron_node' }
    const CYCLOTRON_TABLES = ['cyclotron_jobs', 'cyclotron_email_team_seq', 'conversion_watchers']

    type Lock = { client: PoolClient; pid: number }
    type StallableProxy = { url: string; stall: () => void; close: () => Promise<void> }

    let admin: Pool
    let schema: string
    let db: Pool
    let queueName: string
    let teamId: number
    let queues: CyclotronJobQueuePostgresV2[]
    let locks: Lock[]
    let proxies: StallableProxy[]

    const dbUrl = (host: string, port: number): string => {
        const url = new URL(`postgres://posthog:posthog@${host}:${port}/${CYCLOTRON_DB.database}`)
        url.searchParams.set('options', `-c search_path=${schema},public`)
        return url.toString()
    }

    beforeAll(() => {
        admin = new Pool({
            connectionString: `postgres://posthog:posthog@${CYCLOTRON_DB.host}:${CYCLOTRON_DB.port}/${CYCLOTRON_DB.database}`,
        })
    })

    afterAll(async () => {
        await admin.end()
    })

    beforeEach(async () => {
        schema = `job_queue_test_${uuidv4().replace(/-/g, '')}`
        await admin.query(`CREATE SCHEMA ${schema}`)
        for (const table of CYCLOTRON_TABLES) {
            await admin.query(`CREATE TABLE ${schema}.${table} (LIKE public.${table} INCLUDING ALL)`)
        }
        db = new Pool({ connectionString: dbUrl(CYCLOTRON_DB.host, CYCLOTRON_DB.port) })
        queueName = `job-queue-v2-test-${uuidv4()}`
        teamId = 1_000_000 + Math.floor(Math.random() * 1_000_000_000)
        queues = []
        locks = []
        proxies = []
    })

    afterEach(async () => {
        jest.useRealTimers()
        jest.restoreAllMocks()
        await Promise.all(proxies.map((proxy) => proxy.close()))
        for (const lock of locks) {
            await lock.client.query('ROLLBACK')
            lock.client.release()
        }
        for (const queue of queues) {
            await queue.stopConsumer()
            await queue.stopProducer()
        }
        await db.end()
        await admin.query(`DROP SCHEMA ${schema} CASCADE`)
    })

    const otherTeamId = (): number => teamId + 1

    async function startQueue(url = dbUrl(CYCLOTRON_DB.host, CYCLOTRON_DB.port)) {
        const queue = new CyclotronJobQueuePostgresV2(10, {
            CYCLOTRON_NODE_DATABASE_URL: url,
            CYCLOTRON_SHARD_DEPTH_LIMIT: 1_000_000,
            CDP_CYCLOTRON_BATCH_DELAY_MS: 10,
            CDP_CYCLOTRON_BOUNDED_POLLS: false,
            CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE: 1000,
            CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES: false,
            CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '',
            ENCRYPTION_SALT_KEYS,
        })
        queues.push(queue)
        await queue.startAsProducer()
        return queue
    }

    async function enqueue(
        queue: CyclotronJobQueuePostgresV2,
        overrides: Partial<CyclotronJobInvocation> = {}
    ): Promise<string> {
        const id = uuidv7()
        await queue.queueInvocations([
            { ...baseInvocation, id, teamId, queue: queueName as CyclotronJobQueueKind, ...overrides },
        ])
        return id
    }

    async function consume(
        queue: CyclotronJobQueuePostgresV2,
        from: string,
        work: (invocations: CyclotronJobInvocation[]) => Promise<unknown> = () => Promise.resolve()
    ): Promise<{ claimed: (count?: number) => Promise<CyclotronJobInvocation[]> }> {
        const claims: CyclotronJobInvocation[] = []
        await queue.startAsConsumer(from as CyclotronJobQueueKind, (invocations) => {
            claims.push(...invocations)
            return Promise.resolve({ backgroundTask: invocations.length ? work(invocations) : Promise.resolve() })
        })
        return {
            claimed: (count = 1) =>
                waitForExpect(
                    () => {
                        expect(claims.length).toBeGreaterThanOrEqual(count)
                        return claims.slice(0, count)
                    },
                    10_000,
                    10
                ),
        }
    }

    const finished = (invocation: CyclotronJobInvocation): CyclotronJobInvocationResult =>
        createResult({ invocation, finished: true })

    const movedToEmail = (invocation: CyclotronJobInvocation): CyclotronJobInvocationResult =>
        createResult({
            invocation: { ...invocation, queue: 'email', queueScheduledAt: DateTime.now().plus({ hours: 1 }) },
        })

    async function jobRow(
        id: string
    ): Promise<{ status: string; queue_name: string; priority: number; scheduled: string }> {
        const { rows } = await db.query(
            'SELECT status, queue_name, priority, scheduled FROM cyclotron_jobs WHERE id = $1',
            [id]
        )
        return rows[0]
    }

    const inAnHour = (): Date => DateTime.now().plus({ hours: 1 }).toJSDate()

    const deferred = (
        invocation: CyclotronJobInvocation
    ): { invocation: CyclotronJobInvocation; scheduledAt: Date } => ({
        invocation,
        scheduledAt: inAnHour(),
    })

    async function lateness(queue: string, wait: 'deferred' | 'scheduled'): Promise<{ count: number; sum: number }> {
        const metric = register.getSingleMetric('cdp_cyclotron_job_lateness_seconds')
        const samples = metric ? (await metric.get()).values : []
        const series = (name: 'count' | 'sum'): number =>
            samples.find(
                (sample) =>
                    'metricName' in sample &&
                    sample.metricName === `cdp_cyclotron_job_lateness_seconds_${name}` &&
                    sample.labels.queue === queue &&
                    sample.labels.wait === wait
            )?.value ?? 0
        return { count: series('count'), sum: series('sum') }
    }

    async function leaseOf(id: string): Promise<bigint> {
        const { rows } = await db.query(
            `SELECT (extract(epoch FROM last_heartbeat) * 1000000)::bigint::text AS lease
                 FROM cyclotron_jobs WHERE id = $1`,
            [id]
        )
        return BigInt(rows[0].lease)
    }

    async function lock(sql: string, params: unknown[]): Promise<Lock> {
        const client = await db.connect()
        await client.query('BEGIN')
        const held = { client, pid: (await client.query('SELECT pg_backend_pid() AS pid')).rows[0].pid }
        locks.push(held)
        await client.query(sql, params)
        return held
    }

    const lockJobRow = (id: string): Promise<Lock> =>
        lock('SELECT 1 FROM cyclotron_jobs WHERE id = $1 FOR UPDATE', [id])

    async function lockEmailSequence(): Promise<Lock> {
        await db.query(
            'INSERT INTO cyclotron_email_team_seq (team_id, counter) VALUES ($1, 1) ON CONFLICT (team_id) DO NOTHING',
            [teamId]
        )
        return lock('SELECT 1 FROM cyclotron_email_team_seq WHERE team_id = $1 FOR UPDATE', [teamId])
    }

    const releaseStaleClaimAsTheJanitorDoes = async (id: string): Promise<void> => {
        await db.query(
            `UPDATE cyclotron_jobs SET status = 'available', lock_id = NULL, last_heartbeat = NULL WHERE id = $1`,
            [id]
        )
    }

    const unlock = async (held: Lock): Promise<void> => {
        await held.client.query('ROLLBACK')
    }

    const writeWaitingOn = (held: Lock): Promise<number> =>
        waitForExpect(
            async () => {
                const { rows } = await db.query(
                    'SELECT pid FROM pg_stat_activity WHERE $1 = ANY(pg_blocking_pids(pid))',
                    [held.pid]
                )
                expect(rows).toHaveLength(1)
                return rows[0].pid as number
            },
            10_000,
            10
        )

    async function dropConnectionOfWriteWaitingOn(held: Lock): Promise<void> {
        await db.query('SELECT pg_terminate_backend($1)', [await writeWaitingOn(held)])
    }

    const PENDING_WINDOW_MS = 250
    const stillPending = (promise: Promise<unknown>): Promise<boolean> =>
        Promise.race([
            promise.then(
                () => false,
                () => false
            ),
            new Promise<boolean>((resolve) => setTimeout(() => resolve(true), PENDING_WINDOW_MS)),
        ])

    async function startStallableProxy(): Promise<StallableProxy> {
        const sockets = new Set<Socket>()
        const server = createServer((client) => {
            const upstream = connect(CYCLOTRON_DB.port, CYCLOTRON_DB.host)
            for (const socket of [client, upstream]) {
                sockets.add(socket)
                socket.on('error', () => undefined)
            }
            client.pipe(upstream)
            upstream.pipe(client)
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        const proxy = {
            url: dbUrl('127.0.0.1', (server.address() as AddressInfo).port),
            stall: () => {
                for (const socket of sockets) {
                    socket.unpipe()
                    socket.pause()
                }
            },
            close: async () => {
                for (const socket of sockets) {
                    socket.destroy()
                }
                await new Promise((resolve) => server.close(resolve))
            },
        }
        proxies.push(proxy)
        return proxy
    }

    function stopBoth(queue: CyclotronJobQueuePostgresV2): { returned: () => boolean; stopped: Promise<void> } {
        let returned = false
        const stopped = queue
            .stopConsumer()
            .then(() => queue.stopProducer())
            .then(() => {
                returned = true
            })
        return { returned: () => returned, stopped }
    }

    const TIMER_SLACK_MS = 5

    const useFakeClock = (): void => {
        jest.useFakeTimers({
            doNotFake: ['nextTick', 'setImmediate', 'clearImmediate', 'queueMicrotask', 'hrtime', 'performance'],
        })
    }

    it.each([
        { from: 'email', to: 'email', persisted: true },
        { from: 'email', to: 'another queue', persisted: true },
        { from: 'another queue', to: 'email', persisted: true },
        { from: 'another queue', to: 'another queue', persisted: false },
    ])(
        'persists the invocation priority on $from -> $to only when the email queue is on either side',
        async ({ from, to, persisted }) => {
            const on = (name: string): CyclotronJobQueueKind =>
                (name === 'email' ? 'email' : queueName) as CyclotronJobQueueKind
            const queue = await startQueue()
            const id = await enqueue(queue, { queue: on(from), queuePriority: 1 })
            const [claimed] = await (await consume(queue, on(from))).claimed()

            await queue.queueInvocationResults([
                createResult({
                    invocation: {
                        ...claimed,
                        queue: on(to),
                        queuePriority: 3,
                        queueScheduledAt: DateTime.now().plus({ hours: 1 }),
                    },
                }),
            ])

            expect(await jobRow(id)).toMatchObject({
                queue_name: on(to),
                priority: persisted ? 3 : 1,
            })
        }
    )

    it.each([
        {
            write: 'result',
            from: 'another queue',
            writeAll: (
                queue: CyclotronJobQueuePostgresV2,
                failing: CyclotronJobInvocation,
                held: CyclotronJobInvocation
            ) => queue.queueInvocationResults([finished(failing), movedToEmail(held)]),
            heldRow: { queue_name: 'email', status: 'available' },
        },
        {
            write: 'deferral',
            from: 'email',
            writeAll: (
                queue: CyclotronJobQueuePostgresV2,
                failing: CyclotronJobInvocation,
                held: CyclotronJobInvocation
            ) => queue.deferInvocations([failing, held].map(deferred)),
            heldRow: { queue_name: 'email', status: 'available' },
        },
    ])(
        'settles once every $write write of the batch settled, then reports the one that failed',
        async ({ from, writeAll, heldRow }) => {
            const on = (from === 'email' ? 'email' : queueName) as CyclotronJobQueueKind
            const queue = await startQueue()
            const failingId = await enqueue(queue, { queue: on, teamId: otherTeamId() })
            const heldId = await enqueue(queue, { queue: on })
            const claims = await (await consume(queue, on)).claimed(2)
            const failingRow = await lockJobRow(failingId)
            const emailSequence = await lockEmailSequence()

            const written = writeAll(
                queue,
                claims.find(({ id }) => id === failingId)!,
                claims.find(({ id }) => id === heldId)!
            )
            await dropConnectionOfWriteWaitingOn(failingRow)
            await writeWaitingOn(emailSequence)
            expect(await stillPending(written)).toBe(true)
            await unlock(emailSequence)

            await expect(written).rejects.toThrow('terminating connection')
            expect(await jobRow(heldId)).toMatchObject(heldRow)
            expect(await jobRow(failingId)).toMatchObject({ status: 'running' })
        }
    )

    it('hands a job back with its deferral state, and counts its next dequeue as late from its first due time', async () => {
        const queue = await startQueue()
        const id = await enqueue(queue)
        const consumer = await consume(queue, queueName)
        const [first] = await consumer.claimed()
        const firstDueAt = Date.now() - 60_000
        const scheduledAt = new Date(Date.now() + 500)

        await queue.deferInvocations([
            {
                invocation: { ...first, queueMetadata: { attachmentDeferrals: 1, attachmentDueAt: firstDueAt } },
                scheduledAt,
            },
        ])
        const [, again] = await consumer.claimed(2)

        expect(again).toMatchObject({ id, queueMetadata: { attachmentDeferrals: 1, attachmentDueAt: firstDueAt } })
        expect(new Date((await jobRow(id)).scheduled)).toEqual(scheduledAt)
        expect(await lateness(queueName, 'scheduled')).toMatchObject({ count: 1 })
        const late = await lateness(queueName, 'deferred')
        expect(late.count).toBe(1)
        expect(late.sum).toBeGreaterThanOrEqual(60)
    })

    it.each([
        ['on', true],
        ['off', false],
    ])(
        'hands a deferred send with files back with its files, its queue metadata and integration inputs that still resolve, with integration refs %s',
        async (_name, integrationRefsOn) => {
            jest.spyOn(posthogUtils, 'isFeatureFlagEnabled').mockResolvedValue(integrationRefsOn)
            const queue = await startQueue()
            await enqueue(queue, { queue: `${queueName}-flag-read` as CyclotronJobQueueKind })
            await new Promise((resolve) => setImmediate(resolve))
            const accessToken = `fake-access-token-${uuidv4()}`
            const files = {
                type: 'email' as const,
                to: { email: 'test@example.com', name: 'Test User' },
                from: { integrationId: 1 },
                subject: 'Your invoice',
                text: 'Attached',
                html: '<p>Attached</p>',
                attachments: [
                    { filename: 'invoice.pdf', contentType: 'application/pdf', sizeBytes: 7, sha256: 'a'.repeat(64) },
                ],
            }
            const id = await enqueue(queue, {
                queueParameters: files,
                queueMetadata: { attachmentLoadRetries: 2, teamBudgetClaimed: true },
                state: {
                    actionStepCount: 1,
                    currentAction: {
                        id: 'send-email',
                        startedAtTimestamp: 0,
                        hogFunctionState: {
                            globals: {
                                inputs: {
                                    oauth: markServerResolvedIntegration({
                                        $integration_id: 11,
                                        access_token_raw: accessToken,
                                    }),
                                },
                            },
                            timings: [],
                            attempts: 0,
                        },
                    },
                },
            })
            const consumer = await consume(queue, queueName)
            const [first] = await consumer.claimed()
            const firstDueAt = Date.now()

            await queue.deferInvocations([
                {
                    invocation: {
                        ...first,
                        queueMetadata: { ...first.queueMetadata, attachmentDeferrals: 1, attachmentDueAt: firstDueAt },
                    },
                    scheduledAt: new Date(Date.now() + 200),
                },
            ])
            const [, again] = await consumer.claimed(2)
            const { rows } = await db.query('SELECT state FROM cyclotron_jobs WHERE id = $1', [id])

            expect(again).toMatchObject({
                id,
                queueParameters: files,
                queueMetadata: {
                    attachmentLoadRetries: 2,
                    teamBudgetClaimed: true,
                    attachmentDeferrals: 1,
                    attachmentDueAt: firstDueAt,
                },
            })
            const integrationStore: IntegrationSource = {
                name: 'test',
                load: (references) =>
                    Promise.resolve(
                        Object.fromEntries(
                            references
                                .filter((reference) => reference === '11')
                                .map((reference) => [
                                    reference,
                                    {
                                        reference,
                                        integration: createIntegration({
                                            id: 11,
                                            team_id: teamId,
                                            kind: 'oauth',
                                            sensitive_config: { access_token: accessToken },
                                        }),
                                        decryptFailures: [],
                                    },
                                ])
                        )
                    ),
            }
            const worker = new HogInputsService(
                new IntegrationManagerService({ on: () => undefined } as unknown as PubSub, integrationStore),
                undefined,
                new EncryptedFields(ENCRYPTION_SALT_KEYS)
            )
            const sendStep = createHogFunction({
                team_id: teamId,
                inputs_schema: [{ key: 'oauth', type: 'integration', required: true }],
                inputs: { oauth: { value: 11 } },
            })
            const resolved = await worker.resolveIntegrationRefs(
                sendStep,
                again.state!.currentAction.hogFunctionState.globals.inputs
            )

            expect(resolved.oauth).toMatchObject({ $integration_id: 11, access_token_raw: accessToken })
            expect(rows[0].state.toString('utf-8').includes(accessToken)).toBe(!integrationRefsOn)
        }
    )

    it('stops dequeuing, then returns once the batch in progress has written its results', async () => {
        const queue = await startQueue()
        const id = await enqueue(queue)
        let finishWork: () => void = () => {}
        const workDone = new Promise<void>((resolve) => (finishWork = resolve))
        await (
            await consume(queue, queueName, (claims) =>
                workDone.then(() => queue.queueInvocationResults(claims.map(finished)))
            )
        ).claimed()

        const stopped = queue.stopConsumer()
        const enqueuedDuringStop = await enqueue(queue)
        expect(await stillPending(stopped)).toBe(true)
        finishWork()
        await stopped

        expect(await jobRow(id)).toMatchObject({ status: 'completed' })
        expect(await jobRow(enqueuedDuringStop)).toMatchObject({ status: 'available' })
    })

    it('waits for every result write of a batch when one of them fails', async () => {
        const queue = await startQueue()
        const failingId = await enqueue(queue)
        const heldId = await enqueue(queue)
        let writeResults: (results: CyclotronJobInvocationResult[]) => void = () => {}
        const claims = await (
            await consume(
                queue,
                queueName,
                () =>
                    new Promise((resolve) => {
                        writeResults = (results) => resolve(queue.queueInvocationResults(results))
                    })
            )
        ).claimed(2)
        const failingRow = await lockJobRow(failingId)
        const emailSequence = await lockEmailSequence()

        writeResults([
            finished(claims.find(({ id }) => id === failingId)!),
            movedToEmail(claims.find(({ id }) => id === heldId)!),
        ])
        await dropConnectionOfWriteWaitingOn(failingRow)
        await writeWaitingOn(emailSequence)
        const stopped = queue.stopConsumer()
        expect(await stillPending(stopped)).toBe(true)
        await unlock(emailSequence)
        await stopped

        expect(await jobRow(heldId)).toMatchObject({ queue_name: 'email', status: 'available' })
    })

    it('returns at the stop deadline, counted from the start of the stop, when the batch in progress takes most of it and its work never finishes', async () => {
        const queue = await startQueue()
        await enqueue(queue)
        let batchArrived: () => void = () => {}
        const arrived = new Promise<void>((resolve) => (batchArrived = resolve))
        let returnBatch: () => void = () => {}
        const batchMayReturn = new Promise<void>((resolve) => (returnBatch = resolve))
        await queue.startAsConsumer(queueName as CyclotronJobQueueKind, async (invocations) => {
            if (invocations.length === 0) {
                return { backgroundTask: Promise.resolve() }
            }
            batchArrived()
            await batchMayReturn
            return { backgroundTask: new Promise(() => {}) }
        })
        await arrived

        useFakeClock()
        const { returned, stopped } = stopBoth(queue)
        await jest.advanceTimersByTimeAsync(20_000)
        returnBatch()
        await jest.advanceTimersByTimeAsync(CONSUMER_STOP_DEADLINE_MS - 20_000 - 1)
        expect(returned()).toBe(false)
        await jest.advanceTimersByTimeAsync(1 + TIMER_SLACK_MS)

        expect(returned()).toBe(true)
        await stopped
    })

    it('returns at the stop deadline, counted from the start of the stop, when the database stops answering mid-write', async () => {
        const proxy = await startStallableProxy()
        const queue = await startQueue(proxy.url)
        await enqueue(queue)
        const [claimed] = await (await consume(queue, queueName)).claimed()

        proxy.stall()
        void queue.queueInvocationResults([finished(claimed)]).catch(() => undefined)
        void enqueue(queue).catch(() => undefined)
        useFakeClock()
        const { returned, stopped } = stopBoth(queue)
        await jest.advanceTimersByTimeAsync(CONSUMER_STOP_DEADLINE_MS - 1)
        expect(returned()).toBe(false)
        await jest.advanceTimersByTimeAsync(1 + TIMER_SLACK_MS)

        expect(returned()).toBe(true)
        await stopped
    })

    const leaseRows = [
        {
            write: 'result',
            from: 'another queue',
            release: (queue: CyclotronJobQueuePostgresV2, claim: CyclotronJobInvocation) =>
                queue.queueInvocationResults([movedToEmail(claim)]),
        },
        {
            write: 'deferral',
            from: 'email',
            release: (queue: CyclotronJobQueuePostgresV2, claim: CyclotronJobInvocation) =>
                queue.deferInvocations([deferred(claim)]),
        },
    ]

    it.each(leaseRows)('renews the lease of a job while its $write write runs', async ({ from, release }) => {
        const on = (from === 'email' ? 'email' : queueName) as CyclotronJobQueueKind
        const queue = await startQueue()
        const id = await enqueue(queue, { queue: on })
        const [claimed] = await (await consume(queue, on)).claimed()
        const emailSequence = await lockEmailSequence()
        const written = release(queue, claimed)
        await writeWaitingOn(emailSequence)
        const leaseBefore = await leaseOf(id)

        await queue.heartbeatInvocations([claimed])

        expect(await leaseOf(id)).toBeGreaterThan(leaseBefore)
        await unlock(emailSequence)
        await written
    })

    it.each(leaseRows)(
        'keeps heartbeating a new claim of the same job once the earlier claim finishes its $write write',
        async ({ from, release }) => {
            const on = (from === 'email' ? 'email' : queueName) as CyclotronJobQueueKind
            const queue = await startQueue()
            const id = await enqueue(queue, { queue: on })
            const consumer = await consume(queue, on)
            const [earlier] = await consumer.claimed()
            const emailSequence = await lockEmailSequence()
            const written = release(queue, earlier)
            await writeWaitingOn(emailSequence)
            await releaseStaleClaimAsTheJanitorDoes(id)
            const [, later] = await consumer.claimed(2)
            await unlock(emailSequence)
            await written
            const leaseBefore = await leaseOf(id)

            await queue.heartbeatInvocations([later])

            expect(await leaseOf(id)).toBeGreaterThan(leaseBefore)
        }
    )
})
