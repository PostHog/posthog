import { DateTime } from 'luxon'
import { register } from 'prom-client'
import { v4 as uuidv4 } from 'uuid'

import { parseJSON } from '~/common/utils/json-parse'

import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../../types'
import { CyclotronV2DequeuedJob } from '../cyclotron-v2'
import {
    CONSUMER_STOP_DEADLINE_MS,
    CyclotronJobQueuePostgresV2,
    extractActionId,
    extractDistinctId,
    extractPersonId,
} from './job-queue-postgres-v2'

jest.mock('../cyclotron-v2', () => ({
    CyclotronV2Manager: jest.fn(),
    CyclotronV2Worker: jest.fn(),
}))

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
            defer: jest.fn().mockResolvedValue(undefined),
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

        it.each([
            { from: 'hog', to: 'email', persisted: 3 },
            { from: 'email', to: 'hogflow', persisted: 3 },
            { from: 'email', to: 'email', persisted: 3 },
            { from: 'hog', to: 'hog', persisted: undefined },
        ] as const)(
            'persists the invocation priority on $from -> $to only when the email queue is on either side',
            async ({ from, to, persisted }) => {
                const { queue } = createQueue()
                const job = createDequeuedJob({ queueName: from })
                ;(queue as any).pendingJobs.set(job.id, job)

                await queue.queueInvocationResults([
                    createResult({ invocation: { ...baseInvocation, id: job.id, queue: to, queuePriority: 3 } }),
                ])

                expect(job.reschedule.mock.calls[0][0].priority).toBe(persisted)
            }
        )

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

        it.each([
            [
                'result',
                'ack',
                (queue: CyclotronJobQueuePostgresV2, ids: string[]) =>
                    queue.queueInvocationResults(
                        ids.map((id) => createResult({ invocation: { ...baseInvocation, id }, finished: true }))
                    ),
            ],
            [
                'deferral',
                'defer',
                (queue: CyclotronJobQueuePostgresV2, ids: string[]) =>
                    queue.deferInvocations(
                        ids.map((id) => ({ invocation: { ...baseInvocation, id }, scheduledAt: new Date() }))
                    ),
            ],
        ] as const)(
            'settles once every %s write of the batch settled, then reports the one that failed',
            async (_, write, writeAll) => {
                const { queue } = createQueue()
                let finishSecond: () => void = () => {}
                const failing = createDequeuedJob({
                    [write]: jest.fn().mockRejectedValue(new Error('connection reset')),
                })
                const pending = createDequeuedJob({
                    [write]: jest.fn(() => new Promise<void>((resolve) => (finishSecond = resolve))),
                })
                for (const job of [failing, pending]) {
                    ;(queue as any).pendingJobs.set(job.id, job)
                }

                const written = writeAll(queue, [failing.id, pending.id])
                let settled = false
                void written.catch(() => undefined).finally(() => (settled = true))
                await new Promise((resolve) => setImmediate(resolve))
                expect(settled).toBe(false)
                finishSecond()

                await expect(written).rejects.toThrow('connection reset')
            }
        )
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

    describe('deferInvocations', () => {
        async function latenessSamples(wait: string, series: 'count' | 'sum' = 'count'): Promise<number> {
            const metric = register.getSingleMetric('cdp_cyclotron_job_lateness_seconds')
            const samples = metric ? (await metric.get()).values : []
            return (
                samples.find(
                    (sample) =>
                        'metricName' in sample &&
                        sample.metricName === `cdp_cyclotron_job_lateness_seconds_${series}` &&
                        sample.labels.queue === 'email' &&
                        sample.labels.wait === wait
                )?.value ?? 0
            )
        }

        it('hands a job back with its deferral state, and counts its next dequeue as late from its first due time', async () => {
            const { queue } = createQueue()
            let consume: (jobs: CyclotronV2DequeuedJob[]) => Promise<void> = () => Promise.resolve()
            jest.spyOn(queue as any, 'createWorker').mockReturnValue({
                connect: (fn: typeof consume) => {
                    consume = fn
                    return Promise.resolve()
                },
            })
            await queue.startAsConsumer('email', () => Promise.resolve({ backgroundTask: Promise.resolve() }))
            const job = createDequeuedJob({ queueName: 'email' })
            ;(queue as any).pendingJobs.set(job.id, job)
            const scheduledAt = new Date(Date.now() + 5_000)

            await queue.deferInvocations([
                {
                    invocation: {
                        ...baseInvocation,
                        id: job.id,
                        queue: 'email',
                        queueMetadata: { attachmentDeferrals: 1, attachmentDueAt: Date.now() - 60_000 },
                    },
                    scheduledAt,
                },
            ])

            expect(job.defer).toHaveBeenCalledWith({ scheduledAt, state: expect.any(Buffer) })
            expect((queue as any).pendingJobs.has(job.id)).toBe(false)
            const [[{ state }]] = job.defer.mock.calls
            const before = {
                deferred: await latenessSamples('deferred'),
                deferredSeconds: await latenessSamples('deferred', 'sum'),
                scheduled: await latenessSamples('scheduled'),
            }
            const dequeued = (overrides: Record<string, any>) =>
                createDequeuedJob({
                    queueName: 'email',
                    scheduled: DateTime.now(),
                    created: DateTime.now(),
                    ...overrides,
                }) as unknown as CyclotronV2DequeuedJob
            await consume([dequeued({ id: job.id, state }), dequeued({})])
            expect(await latenessSamples('deferred')).toBe(before.deferred + 1)
            expect((await latenessSamples('deferred', 'sum')) - before.deferredSeconds).toBeGreaterThanOrEqual(60)
            expect(await latenessSamples('scheduled')).toBe(before.scheduled + 1)
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

    describe('stopConsumer', () => {
        type BatchOptions = {
            stopConsuming?: () => Promise<void>
            disconnect?: () => Promise<void>
            disconnectProducer?: () => Promise<void>
            jobs?: CyclotronV2DequeuedJob[]
        }

        async function consumeOneBatch(
            backgroundTask: (queue: any) => Promise<void>,
            options: BatchOptions = {}
        ): Promise<{ queue: any; steps: string[] }> {
            const { queue } = createQueue()
            const steps: string[] = []
            ;(queue as any).manager.disconnect = async () => {
                steps.push('close producer pool')
                await options.disconnectProducer?.()
            }
            let consume: (jobs: CyclotronV2DequeuedJob[]) => Promise<void> = () => Promise.resolve()
            jest.spyOn(queue as any, 'createWorker').mockReturnValue({
                connect: (fn: typeof consume) => {
                    consume = fn
                    return Promise.resolve()
                },
                stopConsuming: async () => {
                    steps.push('stop dequeuing')
                    await options.stopConsuming?.()
                },
                disconnect: async () => {
                    steps.push('close pool')
                    await options.disconnect?.()
                },
            })
            await queue.startAsConsumer('hog', () => Promise.resolve({ backgroundTask: backgroundTask(queue) }))
            await consume(
                options.jobs ?? [
                    createDequeuedJob({
                        scheduled: DateTime.now(),
                        created: DateTime.now(),
                    }) as unknown as CyclotronV2DequeuedJob,
                ]
            )
            return { queue, steps }
        }

        it('stops dequeuing, waits for the result writes, then closes the pool', async () => {
            let finishWrite: () => void = () => {}
            const { queue, steps } = await consumeOneBatch(
                () =>
                    new Promise<void>((resolve) => {
                        finishWrite = () => {
                            steps.push('results written')
                            resolve()
                        }
                    })
            )

            const stopped = queue.stopConsumer()
            await new Promise((resolve) => setImmediate(resolve))
            finishWrite()
            await stopped

            expect(steps).toEqual(['stop dequeuing', 'results written', 'close pool'])
        })

        it.each<[string, () => Promise<void>, BatchOptions]>([
            ['a result write never settles', () => new Promise<void>(() => {}), {}],
            [
                'the batch in progress takes most of it and its write never settles',
                () => new Promise<void>(() => {}),
                { stopConsuming: () => new Promise<void>((resolve) => setTimeout(resolve, 20_000)) },
            ],
            [
                'closing the pool hangs on a blocked query',
                () => Promise.resolve(),
                { disconnect: () => new Promise<void>(() => {}) },
            ],
            [
                'closing the producer pool hangs on a blocked insert',
                () => Promise.resolve(),
                { disconnectProducer: () => new Promise<void>(() => {}) },
            ],
        ])(
            'returns at the stop deadline, counted from the start of the stop, when %s',
            async (_name, write, options) => {
                jest.useFakeTimers()
                try {
                    const { queue, steps } = await consumeOneBatch(write, options)
                    let returned = false

                    const stopped = queue
                        .stopConsumer()
                        .then(() => queue.stopProducer())
                        .then(() => (returned = true))
                    await jest.advanceTimersByTimeAsync(CONSUMER_STOP_DEADLINE_MS - 1)
                    expect(returned).toBe(false)
                    await jest.advanceTimersByTimeAsync(1)
                    await stopped

                    expect(steps).toEqual(['stop dequeuing', 'close pool', 'close producer pool'])
                } finally {
                    jest.useRealTimers()
                }
            }
        )

        it('waits for every result write of a batch when one of them fails', async () => {
            let finishSecond: () => void = () => {}
            const failing = createDequeuedJob({ ack: jest.fn().mockRejectedValue(new Error('connection reset')) })
            const pending = createDequeuedJob({
                ack: jest.fn(() => new Promise<void>((resolve) => (finishSecond = resolve))),
            })
            const jobs = [failing, pending].map(
                (job) =>
                    ({
                        ...job,
                        scheduled: DateTime.now(),
                        created: DateTime.now(),
                    }) as unknown as CyclotronV2DequeuedJob
            )
            const { queue, steps } = await consumeOneBatch(
                (q) =>
                    q.queueInvocationResults(
                        jobs.map((job) =>
                            createResult({ invocation: { ...baseInvocation, id: job.id }, finished: true })
                        )
                    ),
                { jobs }
            )

            const stopped = queue.stopConsumer()
            await new Promise((resolve) => setImmediate(resolve))
            expect(steps).toEqual(['stop dequeuing'])
            finishSecond()
            await stopped

            expect(steps).toEqual(['stop dequeuing', 'close pool'])
        })
    })

    describe('heartbeatInvocations', () => {
        it('heartbeats a job until its result write settles', async () => {
            const { queue } = createQueue()
            let finishWrite: () => void = () => {}
            const job = createDequeuedJob({
                ack: jest.fn(() => new Promise<void>((resolve) => (finishWrite = resolve))),
            })
            ;(queue as any).pendingJobs.set(job.id, job)
            const invocation = { ...baseInvocation, id: job.id }

            const written = queue.queueInvocationResults([createResult({ invocation, finished: true })])
            await queue.heartbeatInvocations([invocation])
            finishWrite()
            await written
            await queue.heartbeatInvocations([invocation])

            expect(job.heartbeat).toHaveBeenCalledTimes(1)
        })

        it('keeps heartbeating a new claim of the same job once the earlier claim finishes writing', async () => {
            const { queue } = createQueue()
            let finishWrite: () => void = () => {}
            const earlier = createDequeuedJob({
                ack: jest.fn(() => new Promise<void>((resolve) => (finishWrite = resolve))),
            })
            const later = createDequeuedJob({ id: earlier.id })
            ;(queue as any).pendingJobs.set(earlier.id, earlier)
            const invocation = { ...baseInvocation, id: earlier.id }

            const written = queue.queueInvocationResults([createResult({ invocation, finished: true })])
            ;(queue as any).pendingJobs.set(later.id, later)
            finishWrite()
            await written
            await queue.heartbeatInvocations([invocation])

            expect(later.heartbeat).toHaveBeenCalledTimes(1)
        })

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
})
