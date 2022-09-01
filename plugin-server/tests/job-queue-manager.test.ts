import { RetryError } from '@posthog/plugin-scaffold'

import { runRetriableFunction } from '../src/utils/retries'
import { UUID } from '../src/utils/utils'
import { PromiseManager } from '../src/worker/vm/promise-manager'
import { JobQueueManager } from './../src/main/job-queues/job-queue-manager'
import { EnqueuedJob, Hub, JobName } from './../src/types'

jest.mock('../src/utils/retries')
jest.mock('../src/utils/status')

const mockHub: Hub = {
    instanceId: new UUID('F8B2F832-6639-4596-ABFC-F9664BC88E84'),
    promiseManager: new PromiseManager({ MAX_PENDING_PROMISES_PER_WORKER: 1 } as any),
    JOB_QUEUES: 'fs',
} as Hub

describe('JobQueueManager', () => {
    let jobQueueManager: JobQueueManager
    beforeEach(() => {
        jest.clearAllMocks()
        jobQueueManager = new JobQueueManager(mockHub)
    })

    describe('enqueue()', () => {
        it('calls runRetriableFunction with the correct parameters', async () => {
            await jobQueueManager.enqueue(JobName.PLUGIN_JOB, { type: 'foo' } as EnqueuedJob)
            expect(runRetriableFunction).toHaveBeenCalled()
            const runRetriableFunctionArgs = jest.mocked(runRetriableFunction).mock.calls[0][0]

            expect(runRetriableFunctionArgs.metricName).toEqual('job_queues_enqueue')
            expect(runRetriableFunctionArgs.payload).toEqual({ type: 'foo' })
            expect(runRetriableFunctionArgs.metricTags).toEqual({ jobName: 'pluginJob', pluginServerMode: 'full' })
            expect(runRetriableFunctionArgs.tryFn).not.toBeUndefined()
            expect(runRetriableFunctionArgs.catchFn).not.toBeUndefined()
            expect(runRetriableFunctionArgs.finallyFn).toBeUndefined()
        })
    })

    describe('_enqueue()', () => {
        it('enqueues jobs to the first available job queue', async () => {
            jobQueueManager.jobQueues = [{ enqueue: jest.fn() } as any, { enqueue: jest.fn() } as any]

            await jobQueueManager._enqueue(JobName.PLUGIN_JOB, { type: 'foo', timestamp: Date.now() } as EnqueuedJob)

            // we never reach the second queue
            expect(jobQueueManager.jobQueues[0].enqueue).toHaveBeenCalled()
            expect(jobQueueManager.jobQueues[1].enqueue).not.toHaveBeenCalled()

            jobQueueManager.jobQueues[0].enqueue = jest.fn(() => {
                throw new Error()
            })
            await jobQueueManager._enqueue(JobName.PLUGIN_JOB, { type: 'foo', timestamp: Date.now() } as EnqueuedJob)

            // now after the first queue threw, we enqueue to the second queue
            expect(jobQueueManager.jobQueues[1].enqueue).toHaveBeenCalled()
        })

        it('throws a RetryError if it cannot enqueue the job on any queue', async () => {
            jobQueueManager.jobQueues[0].enqueue = jest.fn(() => {
                throw new Error()
            })

            await expect(
                jobQueueManager._enqueue(JobName.PLUGIN_JOB, { type: 'foo', timestamp: Date.now() } as EnqueuedJob)
            ).rejects.toThrowError(new RetryError('No JobQueue available'))
        })
    })
})
