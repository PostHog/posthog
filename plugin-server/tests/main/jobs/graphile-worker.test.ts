import { GraphileWorker } from '../../../src/main/jobs/graphile-worker'
import { EnqueuedJob, Hub, JobName } from '../../../src/types'
import { runRetriableFunction } from '../../../src/utils/retries'
import { UUID } from '../../../src/utils/utils'
import { PromiseManager } from '../../../src/worker/vm/promise-manager'

jest.mock('../../../src/utils/retries')
jest.mock('../../../src/utils/status')

const mockHub: Hub = {
    instanceId: new UUID('F8B2F832-6639-4596-ABFC-F9664BC88E84'),
    promiseManager: new PromiseManager({ MAX_PENDING_PROMISES_PER_WORKER: 1 } as any),
    JOB_QUEUES: 'fs',
} as Hub

describe('graphileWorker', () => {
    let graphileWorker: GraphileWorker
    beforeEach(() => {
        jest.clearAllMocks()
        graphileWorker = new GraphileWorker(mockHub)
    })

    describe('enqueue()', () => {
        it('calls runRetriableFunction with the correct parameters if retryOnFailure=true', async () => {
            jest.spyOn(graphileWorker, '_enqueue').mockImplementation(() => Promise.resolve())
            await graphileWorker.enqueue(JobName.PLUGIN_JOB, { type: 'foo' } as EnqueuedJob, undefined, true)
            expect(runRetriableFunction).toHaveBeenCalled()
            const runRetriableFunctionArgs = jest.mocked(runRetriableFunction).mock.calls[0][0]

            expect(runRetriableFunctionArgs.metricName).toEqual('job_queues_enqueue')
            expect(runRetriableFunctionArgs.payload).toEqual({ type: 'foo' })
            expect(runRetriableFunctionArgs.metricTags).toEqual({ jobName: 'pluginJob' })
            expect(runRetriableFunctionArgs.tryFn).not.toBeUndefined()
            expect(runRetriableFunctionArgs.catchFn).not.toBeUndefined()
            expect(runRetriableFunctionArgs.finallyFn).toBeUndefined()
        })
    })
})
