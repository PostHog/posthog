import { DateTime } from 'luxon'
import { AddressInfo, Socket, connect, createServer } from 'node:net'
import { Pool, PoolClient } from 'pg'
import { register } from 'prom-client'
import { v4 as uuidv4, v7 as uuidv7 } from 'uuid'

import { parseJSON } from '~/common/utils/json-parse'
import { waitForExpect } from '~/tests/helpers/expectations'

import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'
import { CyclotronV2DequeuedJob } from '../cyclotron-v2'
import {
    CONSUMER_STOP_DEADLINE_MS,
    CyclotronJobQueuePostgresV2,
    extractActionId,
    extractDistinctId,
    extractPersonId,
} from './job-queue-postgres-v2'

describe('CyclotronJobQueuePostgresV2', () => {
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

    function createQueue() {
        const config: any = {
            CYCLOTRON_NODE_DATABASE_URL: 'postgres://test',
            CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE: 1000,
            CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES: false,
        }
        const queue = new CyclotronJobQueuePostgresV2(500, config)

        const bulkCreateJobs = jest.fn().mockResolvedValue(undefined)
        ;(queue as any).manager = { bulkCreateJobs }

        return { queue, bulkCreateJobs }
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

    function createDequeuedJob(overrides: Partial<Record<string, any>> = {}) {
        return {
            id: uuidv4(),
            teamId: 1,
            functionId: '0196a6b9-1104-0000-f099-9cf11985a307',
            queueName: 'hog',
            priority: 0,
            scheduled: new Date(),
            created: new Date(),
            parentRunId: null,
            transitionCount: 0,
            state: null,
            ack: jest.fn().mockResolvedValue(undefined),
            fail: jest.fn().mockResolvedValue(undefined),
            reschedule: jest.fn().mockResolvedValue(undefined),
            cancel: jest.fn().mockResolvedValue(undefined),
            heartbeat: jest.fn().mockResolvedValue(undefined),
            ...overrides,
        }
    }

    describe('extractDistinctId', () => {
        const cases: Array<[string, any, string | null]> = [
            [
                'returns event.distinct_id when present',
                { state: { event: { distinct_id: 'user-from-event' } } },
                'user-from-event',
            ],
            ['returns null when state has no event', { state: { personId: 'p' } }, null],
            ['returns null when state is null', { state: null }, null],
            ['returns null when state is undefined', { state: undefined }, null],
            ['returns null for empty event.distinct_id', { state: { event: { distinct_id: '' } } }, null],
        ]
        it.each(cases)('%s', (_desc, overrides, expected) => {
            const invocation = { ...baseInvocation, id: uuidv4(), ...overrides } as CyclotronJobInvocation
            expect(extractDistinctId(invocation)).toBe(expected)
        })
    })

    describe('extractPersonId', () => {
        const cases: Array<[string, any, string | null]> = [
            [
                'returns invocation.person.id when present (event-triggered)',
                { person: { id: 'person-from-event' }, state: {} },
                'person-from-event',
            ],
            [
                'falls back to state.personId (batch-triggered)',
                { state: { personId: 'person-from-batch' } },
                'person-from-batch',
            ],
            [
                'prefers invocation.person.id over state.personId',
                { person: { id: 'person-from-event' }, state: { personId: 'person-from-batch' } },
                'person-from-event',
            ],
            ['returns null when neither is present', { state: { globals: {} } }, null],
            ['returns null when state is null', { state: null }, null],
            ['returns null when state is undefined', { state: undefined }, null],
            ['falls through empty person.id to state.personId', { person: { id: '' }, state: { personId: 'p' } }, 'p'],
        ]
        it.each(cases)('%s', (_desc, overrides, expected) => {
            const invocation = { ...baseInvocation, id: uuidv4(), ...overrides } as CyclotronJobInvocation
            expect(extractPersonId(invocation)).toBe(expected)
        })
    })

    describe('extractActionId', () => {
        const cases: Array<[string, Partial<CyclotronJobInvocation>, string | null]> = [
            [
                'returns currentAction.id when present',
                { state: { currentAction: { id: 'action-uuid' } } as any },
                'action-uuid',
            ],
            ['returns null when currentAction is absent', { state: { event: {} } as any }, null],
            ['returns null when state is null', { state: null as any }, null],
            ['returns null when state is undefined', { state: undefined as any }, null],
            ['returns null when currentAction.id is empty', { state: { currentAction: { id: '' } } as any }, null],
        ]
        it.each(cases)('%s', (_desc, overrides, expected) => {
            const invocation = { ...baseInvocation, id: uuidv4(), ...overrides } as CyclotronJobInvocation
            expect(extractActionId(invocation)).toBe(expected)
        })
    })

    describe('queueInvocations', () => {
        it('should serialize state into a Buffer', async () => {
            const { queue, bulkCreateJobs } = createQueue()
            const id = uuidv4()

            await queue.queueInvocations([{ ...baseInvocation, id }])

            expect(bulkCreateJobs).toHaveBeenCalledTimes(1)
            const jobs = bulkCreateJobs.mock.calls[0][0]
            expect(jobs).toHaveLength(1)
            expect(jobs[0].id).toBe(id)
            expect(jobs[0].teamId).toBe(1)
            expect(jobs[0].queueName).toBe('hog')

            const stateBlob = parseJSON(jobs[0].state.toString('utf-8'))
            expect(stateBlob.state).toEqual(baseInvocation.state)
        })

        it('should include queueParameters and queueMetadata in serialized state', async () => {
            const { queue, bulkCreateJobs } = createQueue()

            await queue.queueInvocations([
                {
                    ...baseInvocation,
                    id: uuidv4(),
                    queueParameters: { type: 'fetch', url: 'https://example.com', method: 'GET' } as any,
                    queueMetadata: { retryCount: 2 } as any,
                },
            ])

            const stateBlob = parseJSON(bulkCreateJobs.mock.calls[0][0][0].state.toString('utf-8'))
            expect(stateBlob.queueParameters).toEqual({ type: 'fetch', url: 'https://example.com', method: 'GET' })
            expect(stateBlob.queueMetadata).toEqual({ retryCount: 2 })
        })

        it('forwards extracted distinctId, personId and actionId to bulkCreateJobs', async () => {
            const { queue, bulkCreateJobs } = createQueue()
            await queue.queueInvocations([
                {
                    ...baseInvocation,
                    id: uuidv4(),
                    person: { id: 'event-person' },
                    state: { event: { distinct_id: 'd-1' }, currentAction: { id: 'a-1' } } as any,
                } as any,
                { ...baseInvocation, id: uuidv4(), state: { personId: 'batch-person' } as any },
                { ...baseInvocation, id: uuidv4() },
            ])
            const jobs = bulkCreateJobs.mock.calls[0][0]
            expect(jobs.map((j: any) => j.distinctId)).toEqual(['d-1', null, null])
            expect(jobs.map((j: any) => j.personId)).toEqual(['event-person', 'batch-person', null])
            expect(jobs.map((j: any) => j.actionId)).toEqual(['a-1', null, null])
        })

        it('should not call bulkCreateJobs for empty invocations', async () => {
            const { queue, bulkCreateJobs } = createQueue()

            await queue.queueInvocations([])

            expect(bulkCreateJobs).not.toHaveBeenCalled()
        })

        it('should throw if manager not initialized', async () => {
            const config: any = {
                CYCLOTRON_NODE_DATABASE_URL: 'postgres://test',
                CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE: 1000,
            }
            const queue = new CyclotronJobQueuePostgresV2(500, config)

            await expect(queue.queueInvocations([{ ...baseInvocation, id: uuidv4() }])).rejects.toThrow(
                'CyclotronV2Manager not initialized'
            )
        })
    })

    describe('queueInvocationResults', () => {
        it('should call ack on finished jobs', async () => {
            const { queue } = createQueue()
            const job = createDequeuedJob()
            ;(queue as any).pendingJobs.set(job.id, job)

            await queue.queueInvocationResults([
                createResult({ invocation: { ...baseInvocation, id: job.id }, finished: true }),
            ])

            expect(job.ack).toHaveBeenCalledTimes(1)
            expect((queue as any).pendingJobs.has(job.id)).toBe(false)
        })

        it('should call fail on errored jobs', async () => {
            const { queue } = createQueue()
            const job = createDequeuedJob()
            ;(queue as any).pendingJobs.set(job.id, job)

            await queue.queueInvocationResults([
                createResult({ invocation: { ...baseInvocation, id: job.id }, error: 'something broke' }),
            ])

            expect(job.fail).toHaveBeenCalledTimes(1)
        })

        it('should call cancel, not ack, on canceled jobs so they never count as completed', async () => {
            const { queue } = createQueue()
            const job = createDequeuedJob()
            ;(queue as any).pendingJobs.set(job.id, job)

            await queue.queueInvocationResults([
                createResult({ invocation: { ...baseInvocation, id: job.id }, finished: true, canceled: true }),
            ])

            expect(job.cancel).toHaveBeenCalledTimes(1)
            expect(job.ack).not.toHaveBeenCalled()
            expect((queue as any).pendingJobs.has(job.id)).toBe(false)
        })

        it('should call reschedule with serialized state on non-finished, non-errored jobs', async () => {
            const { queue } = createQueue()
            const job = createDequeuedJob()
            ;(queue as any).pendingJobs.set(job.id, job)

            await queue.queueInvocationResults([createResult({ invocation: { ...baseInvocation, id: job.id } })])

            expect(job.reschedule).toHaveBeenCalledTimes(1)
            const retryArg = job.reschedule.mock.calls[0][0]
            const parsed = parseJSON(retryArg.state.toString('utf-8'))
            expect(parsed.state).toEqual(baseInvocation.state)
        })

        it('should pass scheduledAt when queueScheduledAt is set', async () => {
            const { queue } = createQueue()
            const job = createDequeuedJob()
            ;(queue as any).pendingJobs.set(job.id, job)

            const scheduledAt = DateTime.now().plus({ seconds: 30 })

            await queue.queueInvocationResults([
                createResult({
                    invocation: { ...baseInvocation, id: job.id, queueScheduledAt: scheduledAt },
                }),
            ])

            expect(job.reschedule).toHaveBeenCalledTimes(1)
            const retryArg = job.reschedule.mock.calls[0][0]
            expect(retryArg.scheduledAt).toEqual(scheduledAt.toJSDate())
        })

        it('should pass undefined scheduledAt when queueScheduledAt is not set', async () => {
            const { queue } = createQueue()
            const job = createDequeuedJob()
            ;(queue as any).pendingJobs.set(job.id, job)

            await queue.queueInvocationResults([createResult({ invocation: { ...baseInvocation, id: job.id } })])

            expect(job.reschedule).toHaveBeenCalledTimes(1)
            const retryArg = job.reschedule.mock.calls[0][0]
            expect(retryArg.scheduledAt).toBeUndefined()
        })

        it('should create new job when no pending job found and not finished/errored', async () => {
            const { queue, bulkCreateJobs } = createQueue()
            const id = uuidv4()

            await queue.queueInvocationResults([createResult({ invocation: { ...baseInvocation, id } })])

            expect(bulkCreateJobs).toHaveBeenCalledTimes(1)
        })

        it('should not create new job when no pending job found but finished', async () => {
            const { queue, bulkCreateJobs } = createQueue()
            const id = uuidv4()

            await queue.queueInvocationResults([
                createResult({ invocation: { ...baseInvocation, id }, finished: true }),
            ])

            expect(bulkCreateJobs).not.toHaveBeenCalled()
        })
    })

    describe('dequeueInvocations', () => {
        it('should call fail and remove from pending', async () => {
            const { queue } = createQueue()
            const job = createDequeuedJob()
            ;(queue as any).pendingJobs.set(job.id, job)

            await queue.dequeueInvocations([{ ...baseInvocation, id: job.id }])

            expect(job.fail).toHaveBeenCalledTimes(1)
            expect((queue as any).pendingJobs.has(job.id)).toBe(false)
        })

        it('should be a no-op for unknown job ids', async () => {
            const { queue } = createQueue()

            await queue.dequeueInvocations([{ ...baseInvocation, id: uuidv4() }])

            expect((queue as any).pendingJobs.size).toBe(0)
        })
    })

    describe('releaseInvocations', () => {
        it('should call ack and remove from pending', async () => {
            const { queue } = createQueue()
            const job = createDequeuedJob()
            ;(queue as any).pendingJobs.set(job.id, job)

            await queue.releaseInvocations([{ ...baseInvocation, id: job.id }])

            expect(job.ack).toHaveBeenCalledTimes(1)
            expect((queue as any).pendingJobs.has(job.id)).toBe(false)
        })
    })

    describe('startAsConsumer', () => {
        async function failedResultWrites(queue: string): Promise<number> {
            const metric = register.getSingleMetric('cdp_cyclotron_v2_result_write_failures_total')
            const samples = metric ? (await metric.get()).values : []
            return samples.find((sample) => sample.labels.queue === queue)?.value ?? 0
        }

        it('keeps the process up when writing a batch result fails on a dropped connection', async () => {
            const { queue } = createQueue()
            let consume: (jobs: CyclotronV2DequeuedJob[]) => Promise<void> = () => Promise.resolve()
            jest.spyOn(queue as any, 'createWorker').mockReturnValue({
                connect: (fn: typeof consume) => {
                    consume = fn
                    return Promise.resolve()
                },
            })
            const unhandled = jest.fn()
            process.on('unhandledRejection', unhandled)
            try {
                await queue.startAsConsumer('hog', () =>
                    Promise.resolve({ backgroundTask: Promise.reject(new Error('Connection terminated unexpectedly')) })
                )
                const before = await failedResultWrites('hog')
                await consume([
                    createDequeuedJob({
                        scheduled: DateTime.now(),
                        created: DateTime.now(),
                    }) as unknown as CyclotronV2DequeuedJob,
                ])
                await new Promise((resolve) => setImmediate(resolve))
                expect(unhandled).not.toHaveBeenCalled()
                expect(await failedResultWrites('hog')).toBe(before + 1)
            } finally {
                process.off('unhandledRejection', unhandled)
            }
        })
    })

    describe('heartbeatInvocations', () => {
        it('proxies to heartbeat, skips unknown ids, and distinguishes released races from real failures', async () => {
            const { queue } = createQueue()
            const warnSpy = jest.spyOn(require('~/common/utils/logger').logger, 'warn').mockImplementation(() => {})

            const pending = createDequeuedJob()
            const released = createDequeuedJob({
                heartbeat: jest.fn().mockRejectedValue(new Error(`Job ${'x'} already released, cannot heartbeat`)),
            })
            const brokenPg = createDequeuedJob({
                heartbeat: jest.fn().mockRejectedValue(new Error('Connection terminated unexpectedly')),
            })
            ;(queue as any).pendingJobs.set(pending.id, pending)
            ;(queue as any).pendingJobs.set(released.id, released)
            ;(queue as any).pendingJobs.set(brokenPg.id, brokenPg)

            await expect(
                queue.heartbeatInvocations([
                    { ...baseInvocation, id: pending.id },
                    { ...baseInvocation, id: released.id },
                    { ...baseInvocation, id: brokenPg.id },
                    { ...baseInvocation, id: uuidv4() }, // not in pendingJobs
                ])
            ).resolves.toBeUndefined()

            expect(pending.heartbeat).toHaveBeenCalledTimes(1)
            expect(released.heartbeat).toHaveBeenCalledTimes(1)
            expect(brokenPg.heartbeat).toHaveBeenCalledTimes(1)
            // released-race stays quiet (debug), real Postgres failure gets a warn
            expect(warnSpy).toHaveBeenCalledTimes(1)
            expect(warnSpy).toHaveBeenCalledWith(
                'CyclotronV2 heartbeat failed',
                expect.objectContaining({ error: 'Connection terminated unexpectedly' })
            )
            // pendingJobs is unchanged — heartbeat is not a terminal transition
            expect((queue as any).pendingJobs.size).toBe(3)

            warnSpy.mockRestore()
        })
    })
    describe('on Cyclotron Postgres', () => {
        const CYCLOTRON_DB = { host: 'localhost', port: 5432, database: 'test_cyclotron_node' }
        const dbUrl = (host: string, port: number): string =>
            `postgres://posthog:posthog@${host}:${port}/${CYCLOTRON_DB.database}`

        type Lock = { client: PoolClient; pid: number }
        type StallableProxy = { url: string; stall: () => void; close: () => Promise<void> }

        let db: Pool
        let queueName: string
        let teamId: number
        let jobIds: string[]
        let queues: CyclotronJobQueuePostgresV2[]
        let locks: Lock[]
        let proxies: StallableProxy[]

        beforeAll(() => {
            db = new Pool({ connectionString: dbUrl(CYCLOTRON_DB.host, CYCLOTRON_DB.port) })
        })

        afterAll(async () => {
            await db.end()
        })

        // The database is shared with other suites and runs, so each test owns its queue name,
        // team and jobs, and cleans up only those.
        beforeEach(() => {
            queueName = `job-queue-v2-test-${uuidv4()}`
            teamId = 1_000_000 + Math.floor(Math.random() * 1_000_000_000)
            jobIds = []
            queues = []
            locks = []
            proxies = []
        })

        afterEach(async () => {
            jest.useRealTimers()
            await Promise.all(proxies.map((proxy) => proxy.close()))
            for (const lock of locks) {
                await lock.client.query('ROLLBACK')
                lock.client.release()
            }
            for (const queue of queues) {
                await queue.stopConsumer()
                await queue.stopProducer()
            }
            await db.query('DELETE FROM cyclotron_jobs WHERE id = ANY($1)', [jobIds])
            await db.query('DELETE FROM cyclotron_email_team_seq WHERE team_id = $1', [teamId])
        })

        async function startQueue(url = dbUrl(CYCLOTRON_DB.host, CYCLOTRON_DB.port)) {
            const queue = new CyclotronJobQueuePostgresV2(10, {
                CYCLOTRON_NODE_DATABASE_URL: url,
                CYCLOTRON_SHARD_DEPTH_LIMIT: 1_000_000,
                CDP_CYCLOTRON_BATCH_DELAY_MS: 10,
                CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE: 1000,
                CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES: false,
                CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '',
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
            jobIds.push(id)
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
                const ours = invocations.filter((invocation) => jobIds.includes(invocation.id))
                const others = invocations.filter((invocation) => !jobIds.includes(invocation.id))
                claims.push(...ours)
                // Other suites share the email queue: hand their jobs back as they were.
                const handedBack = queue.queueInvocationResults(
                    others.map((invocation) => createResult({ invocation }))
                )
                return Promise.resolve({
                    backgroundTask: Promise.all([handedBack, ours.length ? work(ours) : undefined]),
                })
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

        async function jobRow(id: string): Promise<{ status: string; queue_name: string; priority: number }> {
            const { rows } = await db.query('SELECT status, queue_name, priority FROM cyclotron_jobs WHERE id = $1', [
                id,
            ])
            return rows[0]
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

        // A move into the email queue first takes the team's next email sequence number, so
        // locking that row holds the move without touching the job row itself.
        async function lockEmailSequence(): Promise<Lock> {
            await db.query(
                'INSERT INTO cyclotron_email_team_seq (team_id, counter) VALUES ($1, 1) ON CONFLICT (team_id) DO NOTHING',
                [teamId]
            )
            return lock('SELECT 1 FROM cyclotron_email_team_seq WHERE team_id = $1 FOR UPDATE', [teamId])
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

        // Proves a promise pending only for this window, which is long enough for a write
        // nobody waits on to finish against a local database.
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

        // Each bounded step left after the deadline still waits one timer turn, which runs 1 ms later.
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

                expect(await jobRow(id)).toMatchObject({ queue_name: on(to), priority: persisted ? 3 : 1 })
            }
        )

        it('settles once every write of the batch settled, then reports the one that failed', async () => {
            const queue = await startQueue()
            const failingId = await enqueue(queue)
            const heldId = await enqueue(queue)
            const claims = await (await consume(queue, queueName)).claimed(2)
            const failingRow = await lockJobRow(failingId)
            const emailSequence = await lockEmailSequence()

            const written = queue.queueInvocationResults([
                finished(claims.find(({ id }) => id === failingId)!),
                movedToEmail(claims.find(({ id }) => id === heldId)!),
            ])
            await dropConnectionOfWriteWaitingOn(failingRow)
            await writeWaitingOn(emailSequence)
            expect(await stillPending(written)).toBe(true)
            await unlock(emailSequence)

            await expect(written).rejects.toThrow('terminating connection')
            expect(await jobRow(heldId)).toMatchObject({ queue_name: 'email', status: 'available' })
            expect(await jobRow(failingId)).toMatchObject({ status: 'running' })
        })

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

        it('renews the lease of a job while its result write runs', async () => {
            const queue = await startQueue()
            const id = await enqueue(queue)
            const [claimed] = await (await consume(queue, queueName)).claimed()
            const emailSequence = await lockEmailSequence()
            const written = queue.queueInvocationResults([movedToEmail(claimed)])
            await writeWaitingOn(emailSequence)
            const leaseBefore = await leaseOf(id)

            await queue.heartbeatInvocations([claimed])

            expect(await leaseOf(id)).toBeGreaterThan(leaseBefore)
            await unlock(emailSequence)
            await written
        })

        it('keeps heartbeating a new claim of the same job once the earlier claim finishes writing', async () => {
            const queue = await startQueue()
            const id = await enqueue(queue)
            const consumer = await consume(queue, queueName)
            const [earlier] = await consumer.claimed()
            const emailSequence = await lockEmailSequence()
            const written = queue.queueInvocationResults([movedToEmail(earlier)])
            await writeWaitingOn(emailSequence)
            // What the janitor does to a job whose claim stopped heartbeating.
            await db.query(
                `UPDATE cyclotron_jobs SET status = 'available', lock_id = NULL, last_heartbeat = NULL WHERE id = $1`,
                [id]
            )
            const [, later] = await consumer.claimed(2)
            await unlock(emailSequence)
            await written
            const leaseBefore = await leaseOf(id)

            await queue.heartbeatInvocations([later])

            expect(await leaseOf(id)).toBeGreaterThan(leaseBefore)
        })
    })
})
