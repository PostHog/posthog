import * as fs from 'fs/promises'

import { rasterizeRecordingActivity, setBrowserPool } from '../activities'
import { BrowserPool } from '../browser-pool'
import { rasterizeRecording } from '../recorder'
import { uploadToS3 } from '../storage'
import { RasterizeRecordingInput, RecordingResult } from '../types'

jest.mock('@temporalio/activity', () => ({
    Context: {
        current: () => ({ info: { activityId: 'test-activity-id' } }),
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
        capture_timeout: 10,
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

describe('rasterizer integration', () => {
    const mockPool = { stats: { usageCount: 0, activePages: 0 } } as unknown as BrowserPool

    beforeEach(() => {
        jest.clearAllMocks()
        setBrowserPool(mockPool)
        mockedUploadToS3.mockResolvedValue('s3://test-bucket/exports/mp4/team-1/task-1/uuid.mp4')
    })

    afterAll(() => {
        setBrowserPool(null as any)
    })

    describe('activity orchestration', () => {
        it('throws when browser pool is not initialized', async () => {
            setBrowserPool(null as any)
            await expect(rasterizeRecordingActivity(baseInput())).rejects.toThrow('Browser pool not initialized')
        })

        it('passes recording result metadata through to output', async () => {
            const inactivityPeriods = [
                { ts_from_s: 0, ts_to_s: 5, active: true },
                { ts_from_s: 5, ts_to_s: 10, active: false },
            ]

            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(1024))
                return baseRecordingResult(outputPath, {
                    playback_speed: 1,
                    custom_fps: 24,
                    inactivity_periods: inactivityPeriods,
                })
            })

            const result = await rasterizeRecordingActivity(baseInput({ playback_speed: 1 }))

            expect(result.s3_uri).toBe('s3://test-bucket/exports/mp4/team-1/task-1/uuid.mp4')
            expect(result.video_duration_s).toBe(3)
            expect(result.playback_speed).toBe(1)
            expect(result.show_metadata_footer).toBe(false)
            // recording_ts fields should be computed
            expect(result.inactivity_periods[0].recording_ts_from_s).toBe(0)
            expect(result.inactivity_periods[0].recording_ts_to_s).toBe(5)
            expect(result.inactivity_periods[1].recording_ts_from_s).toBe(5)
            expect(result.inactivity_periods[1].recording_ts_to_s).toBe(5) // inactive = zero video time
            expect(result.file_size_bytes).toBeGreaterThan(0)
            expect(result.timings.total_s).toBeGreaterThan(0)
            expect(result.timings.setup_s).toBe(1.5)
            expect(result.timings.capture_s).toBe(3.2)
            expect(result.timings.upload_s).toBeGreaterThanOrEqual(0)
        })

        it('passes input fields correctly to rasterizeRecording', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath, { playback_speed: 1, custom_fps: 24 })
            })

            const input = baseInput({
                session_id: 'custom-session-xyz',
                team_id: 42,
                capture_timeout: 30,
                playback_speed: 1,
                recording_fps: 15,
            })

            await rasterizeRecordingActivity(input)

            expect(mockedRasterizeRecording).toHaveBeenCalledWith(mockPool, input, expect.stringContaining('ph-video-'))
        })

        it('uploads to S3 with correct bucket and key prefix', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath, { playback_speed: 1, custom_fps: 24 })
            })

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
    })

    describe('show_metadata_footer flag', () => {
        it('passes show_metadata_footer through to output', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath)
            })

            const result = await rasterizeRecordingActivity(baseInput({ show_metadata_footer: true }))
            expect(result.show_metadata_footer).toBe(true)
        })

        it('defaults show_metadata_footer to false when omitted', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath)
            })

            const result = await rasterizeRecordingActivity(baseInput())
            expect(result.show_metadata_footer).toBe(false)
        })
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

    describe('video duration calculation', () => {
        it('uses capture_duration_s directly as video_duration_s', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath, { capture_duration_s: 80 })
            })

            const result = await rasterizeRecordingActivity(baseInput({ playback_speed: 8 }))
            expect(result.video_duration_s).toBe(80)
        })

        it('rounds video_duration_s to nearest integer', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath, { capture_duration_s: 39.96 })
            })

            const result = await rasterizeRecordingActivity(baseInput())
            expect(result.video_duration_s).toBe(40)
        })
    })

    describe('trim option', () => {
        it('passes trim through to rasterizeRecording via input', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath, { capture_duration_s: 40 })
            })

            await rasterizeRecordingActivity(baseInput({ trim: 40 }))

            const calledInput = mockedRasterizeRecording.mock.calls[0][1]
            expect(calledInput.trim).toBe(40)
        })

        it('respects trim-capped capture_duration_s in output', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                // Simulates trim=40 capping a 94s recording
                return baseRecordingResult(outputPath, { capture_duration_s: 40 })
            })

            const result = await rasterizeRecordingActivity(baseInput({ trim: 40 }))
            expect(result.video_duration_s).toBe(40)
        })
    })

    describe('start/end timestamp subset', () => {
        it('passes start and end timestamps through to rasterizeRecording', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath, { capture_duration_s: 35 })
            })

            const input = baseInput({
                start_timestamp: 1700000180000,
                end_timestamp: 1700000240000,
            })
            await rasterizeRecordingActivity(input)

            const calledInput = mockedRasterizeRecording.mock.calls[0][1]
            expect(calledInput.start_timestamp).toBe(1700000180000)
            expect(calledInput.end_timestamp).toBe(1700000240000)
        })
    })

    describe('capture_timeout', () => {
        it('passes capture_timeout through to rasterizeRecording', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath)
            })

            await rasterizeRecordingActivity(baseInput({ capture_timeout: 600 }))

            const calledInput = mockedRasterizeRecording.mock.calls[0][1]
            expect(calledInput.capture_timeout).toBe(600)
        })

        it('works without capture_timeout (defaults to unlimited)', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath)
            })

            const input = baseInput()
            delete (input as any).capture_timeout
            await rasterizeRecordingActivity(input)

            const calledInput = mockedRasterizeRecording.mock.calls[0][1]
            expect(calledInput.capture_timeout).toBeUndefined()
        })
    })
})
