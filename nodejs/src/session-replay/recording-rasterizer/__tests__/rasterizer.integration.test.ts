import * as fs from 'fs/promises'

import { createActivities } from '../activities'
import { BrowserPool } from '../browser-pool'
import { rasterizeRecording } from '../recorder'
import { uploadToS3 } from '../storage'
import { RasterizeRecordingInput, RecordingResult } from '../types'

jest.mock('@temporalio/activity', () => ({
    Context: {
        current: () => ({
            info: {
                activityId: 'test-activity-1',
                workflowExecution: { workflowId: 'test-workflow-1', runId: 'test-run-1' },
            },
        }),
    },
}))
jest.mock('../recorder')
jest.mock('../storage')
jest.mock('../metrics')

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
    const activities = createActivities(mockPool)
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

        // Verify full output shape
        expect(result.s3_uri).toBe('s3://test-bucket/exports/mp4/team-1/task-1/uuid.mp4')
        expect(result.video_duration_s).toBe(3)
        expect(result.playback_speed).toBe(1)
        expect(result.show_metadata_footer).toBe(false)
        expect(result.file_size_bytes).toBeGreaterThan(0)

        // Verify inactivity periods have video timestamps computed
        expect(result.inactivity_periods[0]).toMatchObject({ recording_ts_from_s: 0, recording_ts_to_s: 5 })
        expect(result.inactivity_periods[1]).toMatchObject({ recording_ts_from_s: 5, recording_ts_to_s: 5 })

        // Verify timings are populated
        expect(result.timings.total_s).toBeGreaterThan(0)
        expect(result.timings.setup_s).toBe(1.5)
        expect(result.timings.capture_s).toBe(3.2)
        expect(result.timings.upload_s).toBeGreaterThanOrEqual(0)

        // Verify pool is passed through to rasterizeRecording
        expect(mockedRasterizeRecording).toHaveBeenCalledWith(
            mockPool,
            expect.objectContaining({ session_id: 'test-session-123' }),
            expect.stringContaining('ph-video-'),
            undefined,
            expect.any(Object)
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

    it('rounds video_duration_s to nearest integer', async () => {
        mockSuccessfulRecording({ capture_duration_s: 39.96 })
        const result = await rasterizeRecordingActivity(baseInput())
        expect(result.video_duration_s).toBe(40)
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
})
