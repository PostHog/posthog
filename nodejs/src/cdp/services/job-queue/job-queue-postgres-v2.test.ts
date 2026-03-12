import { v4 as uuidv4 } from 'uuid'

import { parseJSON } from '~/utils/json-parse'

import { CyclotronJobInvocationResult } from '../../types'
import { CyclotronJobQueuePostgresV2 } from './job-queue-postgres-v2'

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
        const queue = new CyclotronJobQueuePostgresV2(config)

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
            retry: jest.fn().mockResolvedValue(undefined),
            cancel: jest.fn().mockResolvedValue(undefined),
            heartbeat: jest.fn().mockResolvedValue(undefined),
            ...overrides,
        }
    }

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
            const queue = new CyclotronJobQueuePostgresV2(config)

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

        it('should call retry with serialized state on non-finished, non-errored jobs', async () => {
            const { queue } = createQueue()
            const job = createDequeuedJob()
            ;(queue as any).pendingJobs.set(job.id, job)

            await queue.queueInvocationResults([createResult({ invocation: { ...baseInvocation, id: job.id } })])

            expect(job.retry).toHaveBeenCalledTimes(1)
            const retryArg = job.retry.mock.calls[0][0]
            const parsed = parseJSON(retryArg.state.toString('utf-8'))
            expect(parsed.state).toEqual(baseInvocation.state)
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

    describe('cancelInvocations', () => {
        it('should call cancel and remove from pending', async () => {
            const { queue } = createQueue()
            const job = createDequeuedJob()
            ;(queue as any).pendingJobs.set(job.id, job)

            await queue.cancelInvocations([{ ...baseInvocation, id: job.id }])

            expect(job.cancel).toHaveBeenCalledTimes(1)
            expect((queue as any).pendingJobs.has(job.id)).toBe(false)
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
})
