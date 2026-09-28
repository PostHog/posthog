// Renders a recording file without Temporal, recording-api or S3, for offline datasets such as the
// Replay Vision labeling benchmark. See bin/rasterize-recording-file.
import * as fs from 'fs/promises'
import * as path from 'path'
import { parseArgs } from 'util'

import { METADATA_FOOTER_HEIGHT_PX } from '@posthog/replay-headless/protocol'

import { parseJSON } from '~/common/utils/json-parse'

import { BrowserPool } from './capture/browser-pool'
import { playerHtmlCache } from './capture/capture-page'
import { FileBlockSource } from './capture/file-block-source'
import { rasterizeRecording } from './capture/recorder'
import { createLogger } from './logger'
import { videoTimestampsFromFrames } from './postprocess'
import { RasterizeRecordingInput, RasterizeRecordingOutput } from './types'

export type RasterizeFileOutput = Omit<RasterizeRecordingOutput, 's3_uri'> & { video_file: string }

export async function rasterizeFile(
    pool: BrowserPool,
    playerHtml: string,
    inputPath: string,
    outDir: string,
    options: Partial<RasterizeRecordingInput>
): Promise<RasterizeFileOutput> {
    // validateInput requires ids shaped like production ones; nothing reads them for a file source.
    const input: RasterizeRecordingInput = {
        session_id: 'file',
        team_id: 1,
        ...options,
        s3_bucket: '',
        s3_key_prefix: '',
    }
    const format = input.output_format || 'mp4'
    await fs.mkdir(outDir, { recursive: true })
    const videoFile = `video.${format}`
    const log = createLogger({ input: inputPath })

    const result = await rasterizeRecording(pool, input, path.join(outDir, videoFile), playerHtml, () => {}, {
        log,
        blockSource: new FileBlockSource(inputPath),
    })
    const stat = await fs.stat(path.join(outDir, videoFile))
    const output: RasterizeFileOutput = {
        video_file: videoFile,
        video_duration_s: result.capture_duration_s,
        playback_speed: result.playback_speed,
        show_metadata_footer: !!input.show_metadata_footer,
        footer_height_px: input.show_metadata_footer ? METADATA_FOOTER_HEIGHT_PX : 0,
        truncated: result.truncated,
        inactivity_periods: videoTimestampsFromFrames(
            result.inactivity_periods,
            result.frame_session_ms,
            result.output_fps,
            result.pre_roll_frames
        ),
        file_size_bytes: stat.size,
        timings: { ...result.timings, upload_s: 0, total_s: result.timings.setup_s + result.timings.capture_s },
    }
    await fs.writeFile(path.join(outDir, 'rasterize.json'), JSON.stringify(output, null, 2))
    return output
}

async function main(): Promise<void> {
    const { values } = parseArgs({
        options: {
            input: { type: 'string' },
            out: { type: 'string' },
            options: { type: 'string', default: '{}' },
        },
    })
    if (!values.input || !values.out) {
        throw new Error('usage: rasterize-file --input <events.jsonl[.zst]> --out <dir> [--options <json>]')
    }
    const pool = new BrowserPool()
    await pool.launch()
    try {
        const playerHtml = await playerHtmlCache.load()
        const output = await rasterizeFile(pool, playerHtml, values.input, values.out, parseJSON(values.options))
        process.stdout.write(JSON.stringify(output) + '\n')
    } finally {
        await pool.shutdown()
    }
}

if (require.main === module) {
    main().catch((err) => {
        process.stderr.write(`${err?.stack ?? err}\n`)
        process.exit(1)
    })
}
