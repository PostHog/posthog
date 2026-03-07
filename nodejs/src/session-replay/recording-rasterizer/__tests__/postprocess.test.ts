import { execFile } from 'child_process'

import { postProcessToMp4 } from '../postprocess'

jest.mock('child_process', () => ({
    execFile: jest.fn(),
}))

const mockExecFile = execFile as unknown as jest.Mock

describe('postProcessToMp4', () => {
    beforeEach(() => {
        mockExecFile.mockImplementation((...args: any[]) => {
            const cb = args[args.length - 1] as (err: unknown, stdout: string, stderr: string) => void
            cb(null, '', '')
        })
    })

    const baseOpts = {
        inputPath: '/tmp/raw.mp4',
        outputPath: '/tmp/final.mp4',
        preRoll: 2.5,
        recordingDuration: 60,
        playbackSpeed: 1,
        customFps: null,
    }

    it('calls ffmpeg with correct base arguments', async () => {
        await postProcessToMp4(baseOpts)

        expect(mockExecFile).toHaveBeenCalledTimes(1)
        const [cmd, args] = mockExecFile.mock.calls[0]
        expect(cmd).toBe('ffmpeg')
        expect(args).toContain('-ss')
        expect(args).toContain('2.50')
        expect(args).toContain('-t')
        expect(args).toContain('60.00')
        expect(args).toContain('-c:v')
        expect(args).toContain('libx264')
        expect(args).toContain('+faststart')
        expect(args[args.length - 1]).toBe('/tmp/final.mp4')
    })

    it('does not add -vf when playback speed is 1 and no custom fps', async () => {
        await postProcessToMp4(baseOpts)

        const args = mockExecFile.mock.calls[0][1] as string[]
        expect(args).not.toContain('-vf')
    })

    it.each([
        { playbackSpeed: 8, customFps: 24, expectedFilter: 'setpts=8*PTS,fps=3' },
        { playbackSpeed: 4, customFps: 24, expectedFilter: 'setpts=4*PTS,fps=6' },
        { playbackSpeed: 8, customFps: null, expectedFilter: 'setpts=8*PTS' },
        { playbackSpeed: 1, customFps: 30, expectedFilter: 'fps=30' },
    ])(
        'builds video filter "$expectedFilter" for speed=$playbackSpeed fps=$customFps',
        async ({ playbackSpeed, customFps, expectedFilter }) => {
            await postProcessToMp4({ ...baseOpts, playbackSpeed, customFps })

            const args = mockExecFile.mock.calls[0][1] as string[]
            const vfIndex = args.indexOf('-vf')
            expect(vfIndex).toBeGreaterThan(-1)
            expect(args[vfIndex + 1]).toBe(expectedFilter)
        }
    )

    it('throws on ffmpeg failure', async () => {
        mockExecFile.mockImplementation((...args: any[]) => {
            const cb = args[args.length - 1] as (err: unknown, stdout: string, stderr: string) => void
            cb({ code: 1, stderr: 'encoding error' }, '', '')
        })

        await expect(postProcessToMp4(baseOpts)).rejects.toThrow('ffmpeg failed with exit code 1: encoding error')
    })

    it('uses FFMPEG_PATH env var when set', async () => {
        const original = process.env.FFMPEG_PATH
        process.env.FFMPEG_PATH = '/custom/ffmpeg'
        try {
            await postProcessToMp4(baseOpts)
            expect(mockExecFile.mock.calls[0][0]).toBe('/custom/ffmpeg')
        } finally {
            if (original !== undefined) {
                process.env.FFMPEG_PATH = original
            } else {
                delete process.env.FFMPEG_PATH
            }
        }
    })
})
