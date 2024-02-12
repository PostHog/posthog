import { GraphileWorker } from '../../../src/main/graphile-worker/graphile-worker'
import { EnqueuedJob, Hub, JobName } from '../../../src/types'
import { UUID } from '../../../src/utils/utils'

jest.mock('../../../src/utils/retries')
jest.mock('../../../src/utils/status')

jest.mock('graphile-worker', () => {
    const actual = jest.requireActual('graphile-worker')
    return {
        ...actual,
        run: async () => {
            await Promise.resolve()
            return { stop: jest.fn() } as any
        },
    }
})

const mockHub: Hub = {
    instanceId: new UUID('F8B2F832-6639-4596-ABFC-F9664BC88E84'),
    JOB_QUEUES: 'fs',
} as Hub

describe('graphileWorker', () => {
    let graphileWorker: GraphileWorker
    beforeEach(() => {
        jest.clearAllMocks()
        graphileWorker = new GraphileWorker(mockHub)
    })

    describe('enqueue()', () => {
        it('calls _enqueue without retries if retryOnFailure=false', async () => {
            jest.spyOn(graphileWorker, '_enqueue').mockImplementation(() => Promise.resolve())
            await graphileWorker.enqueue(JobName.PLUGIN_JOB, { type: 'foo' } as EnqueuedJob)

            expect(graphileWorker._enqueue).toHaveBeenCalledWith(JobName.PLUGIN_JOB, { type: 'foo' })
        })
    })

    describe('syncState()', () => {
        it('creates a new runner if necessary', async () => {
            jest.spyOn(graphileWorker, 'createPool').mockImplementation(() =>
                Promise.resolve({ end: jest.fn() } as any)
            )
            expect(graphileWorker.consumerPool).toBeNull()
            expect(graphileWorker.runner).toBeNull()

            graphileWorker.started = true

            await graphileWorker.syncState()

            expect(graphileWorker.consumerPool).not.toBeNull()
            expect(graphileWorker.runner).not.toBeNull()
        })

        it('calls end() on consumerPool if the worker is in a stopped state', async () => {
            jest.spyOn(graphileWorker, 'createPool').mockImplementation(() =>
                Promise.resolve({ end: jest.fn() } as any)
            )
            expect(graphileWorker.started).toBeFalsy()

            await graphileWorker.start({})
            await graphileWorker.pause()
            await graphileWorker.syncState()

            expect(graphileWorker.consumerPool!.end).toHaveBeenCalled()
        })
    })

    test('pause()', async () => {
        jest.spyOn(graphileWorker, 'syncState')
        expect(graphileWorker.isPaused()).toBeFalsy()
        await graphileWorker.pause()

        expect(graphileWorker.isPaused()).toBeTruthy()
        expect(graphileWorker.syncState).toHaveBeenCalled()
    })

    test('stop()', async () => {
        jest.spyOn(graphileWorker, 'syncState')
        jest.spyOn(graphileWorker, 'createPool').mockImplementation(() => Promise.resolve({ end: jest.fn() } as any))

        expect(graphileWorker.started).toBeFalsy()
        await graphileWorker.start({})
        expect(graphileWorker.started).toBeTruthy()

        await graphileWorker.stop()
        expect(graphileWorker.started).toBeFalsy()
        expect(graphileWorker.syncState).toHaveBeenCalled()
    })

    test('resumeConsumer()', async () => {
        jest.spyOn(graphileWorker, 'syncState')

        expect(graphileWorker.isPaused()).toBeFalsy()
        await graphileWorker.resumeConsumer()
        expect(graphileWorker.syncState).not.toHaveBeenCalled()

        await graphileWorker.pause()
        expect(graphileWorker.isPaused()).toBeTruthy()

        await graphileWorker.resumeConsumer()
        expect(graphileWorker.isPaused()).toBeFalsy()
        expect(graphileWorker.syncState).toHaveBeenCalled()
    })
})
