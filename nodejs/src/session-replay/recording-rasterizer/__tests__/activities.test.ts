import * as fs from 'fs/promises'

import { BrowserPool } from '../capture/browser-pool'
import { rasterizeRecording } from '../capture/recorder'
import { RasterizationError } from '../errors'
import { uploadToS3 } from '../storage'
import { createActivities } from '../temporal/activities'
import { RasterizeRecordingInput, RecordingResult } from '../types'

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
jest.mock('../storage')
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
const mockedUploadToS3 = uploadToS3 as jest.MockedFunction<typeof uploadToS3>

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

function baseRecordingResult(videoPath: string, overrides: Partial<RecordingResult> = {}): RecordingResult {
    return {
        video_path: videoPath,
        playback_speed: 4,
        capture_duration_s: 3.0,
        frame_count: 72,
        truncated: false,
        inactivity_periods: [{ ts_from_s: 0, ts_to_s: 10, active: true }],
        custom_fps: 3,
        timings: { setup_s: 1.5, capture_s: 3.2 },
        ...overrides,
    }
}

function mockSuccessfulRecording(overrides: Partial<RecordingResult> = {}) {
    mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
        await fs.writeFile(outputPath, Buffer.alloc(1024))
        return baseRecordingResult(outputPath, overrides)
    })
}

describe('rasterizeRecordingActivity', () => {
    const mockPool = { stats: { usageCount: 0, activePages: 0 } } as unknown as BrowserPool
    const playerHtml = '<html>player</html>'
    const activities = createActivities(mockPool, playerHtml)
    const rasterizeRecordingActivity = activities['rasterize-recording']

    beforeEach(() => {
        jest.clearAllMocks()
        mockedUploadToS3.mockResolvedValue('s3://test-bucket/exports/mp4/team-1/task-1/uuid.mp4')
    })

    it('orchestrates recording, upload, and returns complete output', async () => {
        const inactivityPeriods = [
            { ts_from_s: 0, ts_to_s: 5, active: true },
            { ts_from_s: 5, ts_to_s: 10, active: false },
        ]
        mockSuccessfulRecording({
            playback_speed: 1,
            custom_fps: 24,
            inactivity_periods: inactivityPeriods,
        })

        const result = await rasterizeRecordingActivity(baseInput({ playback_speed: 1 }))

        expect(result.s3_uri).toBe('s3://test-bucket/exports/mp4/team-1/task-1/uuid.mp4')
        expect(result.video_duration_s).toBe(3.0)
        expect(result.playback_speed).toBe(1)
        expect(result.show_metadata_footer).toBe(false)
        expect(result.truncated).toBe(false)
        expect(result.file_size_bytes).toBeGreaterThan(0)

        expect(result.inactivity_periods[0]).toMatchObject({ recording_ts_from_s: 0, recording_ts_to_s: 5 })
        expect(result.inactivity_periods[1]).toMatchObject({ recording_ts_from_s: 5, recording_ts_to_s: 5 })

        expect(result.timings.total_s).toBeGreaterThan(0)
        expect(result.timings.setup_s).toBe(1.5)
        expect(result.timings.capture_s).toBe(3.2)
        expect(result.timings.upload_s).toBeGreaterThanOrEqual(0)

        expect(mockedRasterizeRecording).toHaveBeenCalledWith(
            mockPool,
            expect.objectContaining({ session_id: 'test-session-123' }),
            expect.stringContaining('ph-video-'),
            playerHtml,
            undefined,
            expect.any(Object),
            expect.any(Function)
        )
    })

    it('uploads to the specified S3 bucket and key prefix', async () => {
        mockSuccessfulRecording()

        await rasterizeRecordingActivity(
            baseInput({ s3_bucket: 'my-bucket', s3_key_prefix: 'exports/mp4/team-99/task-42' })
        )

        expect(mockedUploadToS3).toHaveBeenCalledWith(
            expect.any(String),
            'my-bucket',
            'exports/mp4/team-99/task-42',
            expect.any(String)
        )
    })

    it('passes show_metadata_footer=true through to output', async () => {
        mockSuccessfulRecording()
        const result = await rasterizeRecordingActivity(baseInput({ show_metadata_footer: true }))
        expect(result.show_metadata_footer).toBe(true)
    })

    it('preserves fractional video_duration_s', async () => {
        mockSuccessfulRecording({ capture_duration_s: 39.96 })
        const result = await rasterizeRecordingActivity(baseInput())
        expect(result.video_duration_s).toBe(39.96)
    })

    describe('temp file cleanup', () => {
        it('cleans up temp file on success', async () => {
            let outputPath: string | undefined
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, path) => {
                outputPath = path
                await fs.writeFile(path, Buffer.alloc(64))
                return baseRecordingResult(path)
            })

            await rasterizeRecordingActivity(baseInput())

            expect(outputPath).toBeDefined()
            await expect(fs.access(outputPath!)).rejects.toThrow()
        })

        it('cleans up temp file on recording failure', async () => {
            mockedRasterizeRecording.mockRejectedValue(new Error('browser crashed'))
            await expect(rasterizeRecordingActivity(baseInput())).rejects.toThrow('browser crashed')
        })

        it('cleans up temp file on S3 upload failure', async () => {
            let outputPath: string | undefined
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, path) => {
                outputPath = path
                await fs.writeFile(path, Buffer.alloc(64))
                return baseRecordingResult(path)
            })
            mockedUploadToS3.mockRejectedValue(new Error('S3 access denied'))

            await expect(rasterizeRecordingActivity(baseInput())).rejects.toThrow('S3 access denied')
            await expect(fs.access(outputPath!)).rejects.toThrow()
        })
    })

    describe('error classification', () => {
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
})
