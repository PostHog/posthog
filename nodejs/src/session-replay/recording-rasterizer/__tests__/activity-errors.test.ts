import { BrowserPool } from '../capture/browser-pool'
import { rasterizeRecording } from '../capture/recorder'
import { RasterizationError } from '../errors'
import { createActivities } from '../temporal/activities'
import { RasterizeRecordingInput } from '../types'

jest.mock('@temporalio/activity', () => ({
    Context: {
        current: () => ({
            info: {
                activityId: 'test-activity-1',
                workflowExecution: { workflowId: 'test-workflow-1', runId: 'test-run-1' },
            },
            heartbeat: jest.fn(),
        }),
    },
}))

jest.mock('@temporalio/common', () => ({
    ApplicationFailure: {
        nonRetryable: jest.fn().mockImplementation((message, type, cause) => {
            const err = new Error(message)
            ;(err as any).type = type
            ;(err as any).cause = cause
            ;(err as any)._isNonRetryable = true
            return err
        }),
    },
}))

jest.mock('../capture/recorder')
jest.mock('../storage', () => ({
    uploadToS3: jest.fn(),
}))
jest.mock('../metrics')
jest.mock('../logger', () => ({
    createLogger: () => ({
        info: jest.fn(),
        warn: jest.fn(),
        error: jest.fn(),
        debug: jest.fn(),
        child: jest.fn().mockReturnThis(),
    }),
}))

const { ApplicationFailure } = require('@temporalio/common')
const mockedRasterizeRecording = rasterizeRecording as jest.MockedFunction<typeof rasterizeRecording>

function baseInput(overrides: Partial<RasterizeRecordingInput> = {}): RasterizeRecordingInput {
    return {
        session_id: 'test-session-123',
        team_id: 1,
        playback_speed: 4,
        s3_bucket: 'test-bucket',
        s3_key_prefix: 'exports/mp4/team-1/task-1',
        ...overrides,
    }
}

describe('toActivityError classification', () => {
    const mockPool = { stats: { usageCount: 0, activePages: 0 } } as unknown as BrowserPool
    const activities = createActivities(mockPool)
    const rasterizeRecordingActivity = activities['rasterize-recording']

    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('wraps non-retryable RasterizationError as ApplicationFailure.nonRetryable', async () => {
        const error = new RasterizationError('No snapshot data', false, 'NO_SNAPSHOTS')
        mockedRasterizeRecording.mockRejectedValue(error)

        await expect(rasterizeRecordingActivity(baseInput())).rejects.toThrow('No snapshot data')

        expect(ApplicationFailure.nonRetryable).toHaveBeenCalledWith('No snapshot data', 'NON_RETRYABLE', error)
    })

    it('re-throws retryable RasterizationError as plain Error (Temporal retries)', async () => {
        const error = new RasterizationError('browser crashed', true, 'PLAYBACK_ERROR')
        mockedRasterizeRecording.mockRejectedValue(error)

        const rejection = rasterizeRecordingActivity(baseInput())
        await expect(rejection).rejects.toThrow('browser crashed')
        await expect(rejection).rejects.toBeInstanceOf(RasterizationError)

        expect(ApplicationFailure.nonRetryable).not.toHaveBeenCalled()
    })

    it('re-throws unknown Error as-is (Temporal retries by default)', async () => {
        const error = new Error('unexpected failure')
        mockedRasterizeRecording.mockRejectedValue(error)

        const rejection = rasterizeRecordingActivity(baseInput())
        await expect(rejection).rejects.toThrow('unexpected failure')
        await expect(rejection).rejects.toBe(error)

        expect(ApplicationFailure.nonRetryable).not.toHaveBeenCalled()
    })

    it('wraps non-Error thrown values into Error', async () => {
        mockedRasterizeRecording.mockRejectedValue('string error')

        const rejection = rasterizeRecordingActivity(baseInput())
        await expect(rejection).rejects.toThrow('string error')
        await expect(rejection).rejects.toBeInstanceOf(Error)
    })
})
