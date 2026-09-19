import { EventEmitter } from 'events'
import { PassThrough } from 'stream'

import {
    assertCaptureIsNotBlank,
    buildProbeArgs,
    countUniformFrames,
} from '~/session-replay/recording-rasterizer/capture/blank-capture'

jest.mock('child_process', () => ({ spawn: jest.fn() }))

const { spawn } = jest.requireMock('child_process')

const PROBE_PIXELS = 64 * 36

function frames(...tones: number[][]): Buffer {
    return Buffer.concat(
        tones.map((tone) => {
            const frame = Buffer.alloc(PROBE_PIXELS, tone[0])
            // Paint the rest of the frame with the remaining tones, so a frame with structure has it.
            for (let i = 1; i < tone.length; i++) {
                frame[i] = tone[i]
            }
            return frame
        })
    )
}

/** A fake ffmpeg that writes `stdout` and then exits with `code`. */
function fakeFfmpeg(stdout: Buffer, code: number): void {
    spawn.mockImplementation(() => {
        const child = new EventEmitter() as any
        child.stdout = new PassThrough()
        child.stderr = new PassThrough()
        child.kill = jest.fn()
        process.nextTick(() => {
            child.stdout.write(stdout)
            child.emit('close', code)
        })
        return child
    })
}

const log = { info: jest.fn(), warn: jest.fn(), error: jest.fn(), debug: jest.fn() } as any

describe('blank capture check', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('counts a frame as uniform only when its luma spread is small', () => {
        // Encoder ringing leaves a couple of levels of spread on a truly solid frame, so a small
        // spread still counts as blank; a frame carrying a painted element does not.
        expect(countUniformFrames(frames([16], [16, 18, 14], [16, 200]))).toEqual({
            sampledFrames: 3,
            uniformFrames: 2,
        })
    })

    it('drops a trailing partial frame rather than reading its missing pixels as blank', () => {
        const buffer = Buffer.concat([frames([16, 200]), Buffer.alloc(PROBE_PIXELS - 1, 16)])

        expect(countUniformFrames(buffer)).toEqual({ sampledFrames: 1, uniformFrames: 0 })
    })

    it('samples across the whole file instead of its opening frames', () => {
        expect(buildProbeArgs('/tmp/out.mp4', 30, false)).toContain('fps=0.4000,scale=64:36,format=gray')
    })

    it('crops the metadata footer off, since it paints even when the replay surface does not', () => {
        const filter = buildProbeArgs('/tmp/out.mp4', 30, true).join(' ')

        expect(filter).toContain('crop=iw:max(ih-32\\,2):0:0')
    })

    it('leaves the sampling filter out when the duration is unusable', () => {
        expect(buildProbeArgs('/tmp/out.mp4', 0, false)).toContain('scale=64:36,format=gray')
    })

    it('fails the capture when every probed frame is one flat tone', async () => {
        fakeFfmpeg(frames([16], [16], [255]), 0)

        await expect(assertCaptureIsNotBlank('/tmp/out.mp4', 30, false, log)).rejects.toMatchObject({
            code: 'BLANK_CAPTURE',
            // A compositor that never painted this attempt can paint on the next one.
            retryable: true,
        })
    })

    it('ships a capture where some frames painted', async () => {
        fakeFfmpeg(frames([16], [16, 200]), 0)

        await expect(assertCaptureIsNotBlank('/tmp/out.mp4', 30, false, log)).resolves.toBeUndefined()
    })

    it('ships the capture when the probe itself fails', async () => {
        // No render is worth discarding because ffmpeg was missing or could not read the file.
        fakeFfmpeg(Buffer.alloc(0), 1)

        await expect(assertCaptureIsNotBlank('/tmp/out.mp4', 30, false, log)).resolves.toBeUndefined()
    })

    it('ships the capture when the probe decodes no frames', async () => {
        fakeFfmpeg(Buffer.alloc(0), 0)

        await expect(assertCaptureIsNotBlank('/tmp/out.mp4', 30, false, log)).resolves.toBeUndefined()
    })
})
