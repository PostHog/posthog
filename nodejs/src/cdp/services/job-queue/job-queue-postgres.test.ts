import { v4 as uuidv4, v7 as uuidv7 } from 'uuid'

import { UUIDT } from '../../../utils/utils'
import { createHogFlowInvocation } from '../hogflows/hogflow-executor.service'
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
        const queue = new CyclotronJobQueuePostgres(500, config)

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

        it.each([
            {
                label: 'UUIDT (pre-fix, non-RFC-4122)',
                getId: () => new UUIDT().toString(),
                versionNibble: '0',
                expectPreserved: false,
            },
            { label: 'uuidv7 (post-fix)', getId: () => uuidv7(), versionNibble: '7', expectPreserved: true },
        ])('handles $label id in V1 Postgres route', async ({ getId, versionNibble, expectPreserved }) => {
            const { queue, bulkCreateJobs } = createQueue()

            const id = getId()
            expect(id[14]).toBe(versionNibble)

            const invocation: any = { ...baseInvocation, id }
            await queue.queueInvocations([invocation])

            const jobsArg = bulkCreateJobs.mock.calls[0][0]
            if (expectPreserved) {
                expect(jobsArg[0].id).toBe(id)
            } else {
                expect(jobsArg[0].id).toBeUndefined()
            }
        })

        it('preserves id minted by createHogFlowInvocation across the V1 Postgres route', async () => {
            const { queue, bulkCreateJobs } = createQueue()

            const hogFlow: any = { id: uuidv7(), team_id: 1, variables: [] }
            const globals: any = { event: { uuid: uuidv7() }, variables: {} }
            const invocation: any = createHogFlowInvocation(globals, hogFlow, {} as any)

            expect(invocation.id[14]).toBe('7')

            await queue.queueInvocations([
                {
                    ...invocation,
                    state: { globals: {}, timings: [], vmState: { bytecodes: {}, stack: [], upvalues: [] } },
                },
            ])

            const jobsArg = bulkCreateJobs.mock.calls[0][0]
            expect(jobsArg[0].id).toBe(invocation.id)
        })
    })
})
