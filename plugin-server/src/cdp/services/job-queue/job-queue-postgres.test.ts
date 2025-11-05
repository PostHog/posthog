import { v4 as uuidv4 } from 'uuid'

import { CyclotronJobQueuePostgres } from './job-queue-postgres'

// Mock external dependency to avoid needing the actual implementation in tests
jest.mock('@posthog/cyclotron', () => ({
    CyclotronManager: jest.fn(),
    CyclotronWorker: jest.fn(),
}))

describe('CyclotronJobQueue - postgres', () => {
    function createQueue() {
        const config: any = {
            CYCLOTRON_DATABASE_URL: 'postgres://test',
            CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE: 1000,
            CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES: false,
        }
        const queue = new CyclotronJobQueuePostgres(config, 'hog' as any, () =>
            Promise.resolve({ backgroundTask: Promise.resolve() })
        )

        const bulkCreateJobs = jest.fn().mockResolvedValue(undefined)
        // Inject a fake manager so queueInvocations can run without connecting
        ;(queue as any).cyclotronManager = {
            bulkCreateJobs,
        }

        return { queue, bulkCreateJobs }
    }

    describe('queueInvocations - isValidUuid behavior', () => {
        const baseInvocation = {
            teamId: 1,
            functionId: '0196a6b9-1104-0000-f099-9cf11985a307',
            queue: 'hog',
            queuePriority: 0,
            state: {
                globals: {},
                timings: [],
                vmState: { bytecodes: {}, stack: [], upvalues: [] },
            },
        }

        it('preserves id when it is a valid UUID', async () => {
            const { queue, bulkCreateJobs } = createQueue()

            const invocation: any = {
                ...baseInvocation,
                id: uuidv4(),
            }

            await queue.queueInvocations([invocation])

            expect(bulkCreateJobs).toHaveBeenCalledTimes(1)
            const jobsArg = bulkCreateJobs.mock.calls[0][0]
            expect(Array.isArray(jobsArg)).toBe(true)
            expect(jobsArg).toHaveLength(1)
            expect(jobsArg[0].id).toBe(invocation.id)
        })

        it('omits id when it is NOT a valid UUID (string)', async () => {
            const { queue, bulkCreateJobs } = createQueue()

            const invocation: any = {
                ...baseInvocation,
                id: '123',
            }

            await queue.queueInvocations([invocation])

            const jobsArg = bulkCreateJobs.mock.calls[0][0]
            expect(jobsArg[0].id).toBeUndefined()
        })

        it('omits id when it is NOT a valid UUID (number)', async () => {
            const { queue, bulkCreateJobs } = createQueue()

            const invocation: any = {
                ...baseInvocation,
                id: 12345,
            }

            await queue.queueInvocations([invocation])

            const jobsArg = bulkCreateJobs.mock.calls[0][0]
            expect(jobsArg[0].id).toBeUndefined()
        })
    })
})
