import { DateTime } from 'luxon'
import { v4 as uuidv4 } from 'uuid'

import { parseJSON } from '~/utils/json-parse'

import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../../types'
import {
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
