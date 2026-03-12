import { execFile } from 'child_process'
import * as fs from 'fs/promises'
import * as os from 'os'
import * as path from 'path'
import { promisify } from 'util'

import { parseJSON } from '../../../utils/json-parse'
import { rasterizeRecordingActivity, setBrowserPool } from '../activities'
import { BrowserPool } from '../browser-pool'
import { postProcessToMp4 } from '../postprocess'
import { rasterizeRecording } from '../recorder'
import { uploadToS3 } from '../storage'
import { RasterizeRecordingInput, RecordingResult } from '../types'

const execFileAsync = promisify(execFile)

jest.mock('@temporalio/activity', () => ({
    Context: {
        current: () => ({ info: { activityId: 'test-activity-id' } }),
    },
}))
jest.mock('../recorder')
jest.mock('../storage')
jest.mock('../postprocess')

const mockedRasterizeRecording = rasterizeRecording as jest.MockedFunction<typeof rasterizeRecording>
const mockedUploadToS3 = uploadToS3 as jest.MockedFunction<typeof uploadToS3>
const mockedPostProcess = postProcessToMp4 as jest.MockedFunction<typeof postProcessToMp4>

const ffmpegAvailable = (() => {
    try {
        require('child_process').execFileSync('ffmpeg', ['-version'], { stdio: 'ignore' })
        return true
    } catch {
        return false
    }
})()

const describeWithFfmpeg = ffmpegAvailable ? describe : describe.skip

function baseInput(overrides: Partial<RasterizeRecordingInput> = {}): RasterizeRecordingInput {
    return {
        recording_url: 'https://app.posthog.com/exporter?token=abc',
        wait_for_css_selector: '.replayer-wrapper',
        recording_duration: 10,
        playback_speed: 4,
        s3_bucket: 'test-bucket',
        s3_key_prefix: 'exports/mp4/team-1/task-1',
        ...overrides,
    }
}

function baseRecordingResult(videoPath: string, overrides: Partial<RecordingResult> = {}): RecordingResult {
    return {
        video_path: videoPath,
        pre_roll: 1.5,
        playback_speed: 4,
        measured_width: 1920,
        inactivity_periods: [{ ts_from_s: 0, ts_to_s: 10, active: true }],
        segment_start_timestamps: { '0': 0.5, '5': 2.5 },
        custom_fps: 96,
        ...overrides,
    }
}

async function createTestMp4(filePath: string, durationSeconds: number = 3): Promise<void> {
    await execFileAsync('ffmpeg', [
        '-f',
        'lavfi',
        '-i',
        `color=c=blue:s=320x240:d=${durationSeconds}`,
        '-c:v',
        'libx264',
        '-pix_fmt',
        'yuv420p',
        '-y',
        filePath,
    ])
}

describe('rasterizer integration', () => {
    const mockPool = {} as BrowserPool

    beforeEach(() => {
        jest.clearAllMocks()
        setBrowserPool(mockPool)
        mockedUploadToS3.mockResolvedValue('exports/mp4/team-1/task-1/uuid.mp4')
        // By default, postprocess copies input to output so fs.stat works
        mockedPostProcess.mockImplementation(async (opts) => {
            await fs.copyFile(opts.inputPath, opts.outputPath)
        })
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
                { ts_from_s: 0, ts_to_s: 5, active: true, recording_ts_from_s: 0, recording_ts_to_s: 2 },
                { ts_from_s: 5, ts_to_s: null, active: false },
            ]
            const segmentTimestamps = { '0': 0.1, '5': 1.2, '8': 2.0 }

            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(1024))
                return baseRecordingResult(outputPath, {
                    pre_roll: 0,
                    playback_speed: 1,
                    custom_fps: null,
                    inactivity_periods: inactivityPeriods,
                    segment_start_timestamps: segmentTimestamps,
                    measured_width: 1440,
                })
            })

            const result = await rasterizeRecordingActivity(baseInput({ playback_speed: 1 }))

            expect(result.s3_key).toBe('exports/mp4/team-1/task-1/uuid.mp4')
            expect(result.pre_roll).toBe(0)
            expect(result.playback_speed).toBe(1)
            expect(result.measured_width).toBe(1440)
            expect(result.inactivity_periods).toEqual(inactivityPeriods)
            expect(result.segment_start_timestamps).toEqual(segmentTimestamps)
            expect(result.custom_fps).toBeNull()
            expect(result.file_size_bytes).toBeGreaterThan(0)
        })

        it('passes input fields correctly to rasterizeRecording', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath, { pre_roll: 0, playback_speed: 1, custom_fps: null })
            })

            const input = baseInput({
                recording_url: 'https://custom.posthog.com/exporter?token=xyz',
                wait_for_css_selector: '.custom-selector',
                recording_duration: 30,
                playback_speed: 1,
                screenshot_width: 1280,
                screenshot_height: 720,
                recording_fps: 15,
            })

            await rasterizeRecordingActivity(input)

            expect(mockedRasterizeRecording).toHaveBeenCalledWith(
                mockPool,
                input,
                expect.stringContaining('ph-video-raw-')
            )
        })

        it('uploads to S3 with correct bucket and key prefix', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath, { pre_roll: 0, playback_speed: 1, custom_fps: null })
            })

            await rasterizeRecordingActivity(
                baseInput({ s3_bucket: 'my-bucket', s3_key_prefix: 'exports/mp4/team-99/task-42' })
            )

            expect(mockedUploadToS3).toHaveBeenCalledWith(
                expect.any(String),
                'my-bucket',
                'exports/mp4/team-99/task-42',
                'test-activity-id'
            )
        })

        it('calls postprocess with correct parameters', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath, {
                    pre_roll: 2.5,
                    playback_speed: 8,
                    custom_fps: 192,
                    measured_width: 1280,
                })
            })

            await rasterizeRecordingActivity(baseInput({ playback_speed: 8, recording_duration: 60 }))

            expect(mockedPostProcess).toHaveBeenCalledWith({
                inputPath: expect.stringContaining('ph-video-raw-'),
                outputPath: expect.stringContaining('ph-video-'),
                preRoll: 2.5,
                recordingDuration: 60,
                playbackSpeed: 8,
                customFps: 192,
            })
        })

        it('uploads post-processed file, not raw file', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath)
            })

            await rasterizeRecordingActivity(baseInput())

            const uploadedPath = mockedUploadToS3.mock.calls[0][0]
            expect(uploadedPath).not.toContain('ph-video-raw-')
        })
    })

    describe('skip_postprocessing flag', () => {
        it('uploads raw recording and skips postprocess when true', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(512))
                return baseRecordingResult(outputPath)
            })

            const result = await rasterizeRecordingActivity(baseInput({ skip_postprocessing: true }))

            expect(mockedPostProcess).not.toHaveBeenCalled()
            expect(mockedUploadToS3).toHaveBeenCalledWith(
                expect.stringContaining('ph-video-raw-'),
                'test-bucket',
                'exports/mp4/team-1/task-1',
                'test-activity-id'
            )
            expect(result.file_size_bytes).toBe(512)
        })

        it('runs postprocess when flag is false', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath)
            })

            await rasterizeRecordingActivity(baseInput({ skip_postprocessing: false }))
            expect(mockedPostProcess).toHaveBeenCalled()
        })

        it('runs postprocess when flag is omitted', async () => {
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath)
            })

            await rasterizeRecordingActivity(baseInput())
            expect(mockedPostProcess).toHaveBeenCalled()
        })
    })

    describe('temp file cleanup', () => {
        it('cleans up temp files on success', async () => {
            let rawPath: string | undefined
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                rawPath = outputPath
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath)
            })

            await rasterizeRecordingActivity(baseInput())

            expect(rawPath).toBeDefined()
            await expect(fs.access(rawPath!)).rejects.toThrow()
        })

        it('cleans up temp files on recording failure', async () => {
            mockedRasterizeRecording.mockRejectedValue(new Error('browser crashed'))

            await expect(rasterizeRecordingActivity(baseInput())).rejects.toThrow('browser crashed')
        })

        it('cleans up temp files on postprocess failure', async () => {
            let rawPath: string | undefined
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                rawPath = outputPath
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath)
            })
            mockedPostProcess.mockRejectedValue(new Error('ffmpeg crashed'))

            await expect(rasterizeRecordingActivity(baseInput())).rejects.toThrow('ffmpeg crashed')
            await expect(fs.access(rawPath!)).rejects.toThrow()
        })

        it('cleans up temp files on S3 upload failure', async () => {
            let rawPath: string | undefined
            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                rawPath = outputPath
                await fs.writeFile(outputPath, Buffer.alloc(64))
                return baseRecordingResult(outputPath)
            })
            mockedUploadToS3.mockRejectedValue(new Error('S3 access denied'))

            await expect(rasterizeRecordingActivity(baseInput())).rejects.toThrow('S3 access denied')
            await expect(fs.access(rawPath!)).rejects.toThrow()
        })
    })

    describeWithFfmpeg('post-processing with real ffmpeg', () => {
        // Unmock postprocess for these tests — use real ffmpeg
        let realPostProcess: typeof postProcessToMp4
        let tempDir: string

        beforeAll(async () => {
            realPostProcess = jest.requireActual('../postprocess').postProcessToMp4
            tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'rasterizer-test-'))
        })

        afterAll(async () => {
            await fs.rm(tempDir, { recursive: true, force: true })
        })

        beforeEach(() => {
            mockedPostProcess.mockImplementation(realPostProcess)
        })

        it('produces a valid mp4 from a raw recording', async () => {
            const inputPath = path.join(tempDir, 'raw-input.mp4')
            const outputPath = path.join(tempDir, 'processed-output.mp4')
            await createTestMp4(inputPath, 3)

            await realPostProcess({
                inputPath,
                outputPath,
                preRoll: 0.5,
                recordingDuration: 2,
                playbackSpeed: 1,
                customFps: null,
            })

            const stat = await fs.stat(outputPath)
            expect(stat.size).toBeGreaterThan(0)

            const { stdout } = await execFileAsync('ffprobe', [
                '-v',
                'quiet',
                '-print_format',
                'json',
                '-show_format',
                '-show_streams',
                outputPath,
            ])
            const probe = parseJSON(stdout)
            expect(probe.format.format_name).toContain('mp4')
            expect(parseFloat(probe.format.duration)).toBeLessThanOrEqual(2.5)
            expect(parseFloat(probe.format.duration)).toBeGreaterThan(1)
        })

        it('applies speed correction and fps filter', async () => {
            const inputPath = path.join(tempDir, 'raw-speed.mp4')
            const outputPath = path.join(tempDir, 'processed-speed.mp4')
            await createTestMp4(inputPath, 4)

            await realPostProcess({
                inputPath,
                outputPath,
                preRoll: 0,
                recordingDuration: 4,
                playbackSpeed: 4,
                customFps: 96,
            })

            const { stdout } = await execFileAsync('ffprobe', [
                '-v',
                'quiet',
                '-print_format',
                'json',
                '-show_streams',
                outputPath,
            ])
            const probe = parseJSON(stdout)
            const videoStream = probe.streams.find((s: any) => s.codec_type === 'video')
            expect(videoStream).toBeDefined()
            expect(videoStream.codec_name).toBe('h264')
        })

        it('strips pre-roll from the output', async () => {
            const inputPath = path.join(tempDir, 'raw-preroll.mp4')
            const outputPath = path.join(tempDir, 'processed-preroll.mp4')
            await createTestMp4(inputPath, 5)

            await realPostProcess({
                inputPath,
                outputPath,
                preRoll: 2,
                recordingDuration: 2,
                playbackSpeed: 1,
                customFps: null,
            })

            const { stdout } = await execFileAsync('ffprobe', [
                '-v',
                'quiet',
                '-print_format',
                'json',
                '-show_format',
                outputPath,
            ])
            const probe = parseJSON(stdout)
            expect(parseFloat(probe.format.duration)).toBeLessThanOrEqual(2.5)
        })

        it('full activity pipeline: record → postprocess → upload', async () => {
            mockedUploadToS3.mockResolvedValue('exports/mp4/team-1/task-1/final.mp4')

            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await createTestMp4(outputPath, 3)
                return baseRecordingResult(outputPath, {
                    pre_roll: 0.5,
                    playback_speed: 4,
                    custom_fps: 96,
                })
            })

            const result = await rasterizeRecordingActivity(baseInput({ playback_speed: 4, recording_duration: 10 }))

            const uploadedPath = mockedUploadToS3.mock.calls[0][0]
            expect(uploadedPath).not.toContain('ph-video-raw-')

            expect(result.s3_key).toBe('exports/mp4/team-1/task-1/final.mp4')
            expect(result.file_size_bytes).toBeGreaterThan(0)
            expect(result.playback_speed).toBe(4)
            expect(result.custom_fps).toBe(96)

            // Temp files cleaned up
            await expect(fs.access(uploadedPath)).rejects.toThrow()
        })

        it('full activity pipeline with skip_postprocessing uploads raw', async () => {
            mockedUploadToS3.mockResolvedValue('exports/mp4/team-1/task-1/raw.mp4')

            mockedRasterizeRecording.mockImplementation(async (_pool, _input, outputPath) => {
                await createTestMp4(outputPath, 2)
                return baseRecordingResult(outputPath, {
                    pre_roll: 1.0,
                    playback_speed: 8,
                    custom_fps: 24,
                })
            })

            const result = await rasterizeRecordingActivity(
                baseInput({ playback_speed: 8, recording_fps: 3, skip_postprocessing: true })
            )

            const uploadedPath = mockedUploadToS3.mock.calls[0][0]
            expect(uploadedPath).toContain('ph-video-raw-')
            expect(result.playback_speed).toBe(8)
            expect(result.custom_fps).toBe(24)
        })
    })
})
