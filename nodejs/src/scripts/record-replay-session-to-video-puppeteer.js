/**
 * Node.js video recording script using Puppeteer + puppeteer-screen-recorder
 * Input JSON:
 * {
 *   "url_to_render": "https://...",
 *   "output_path": "/tmp/video.mp4",
 *   "wait_for_css_selector": ".replayer-wrapper",
 *   "recording_duration": 60,
 *   "screenshot_width": 1920,      // optional
 *   "screenshot_height": 1080,     // optional
 *   "playback_speed": 1,           // optional, default 1
 *   "headless": true               // optional, default true
 * }
 *
 * Output JSON (to stdout):
 * {
 *   "success": true,
 *   "video_path": "/tmp/video.mp4",
 *   "pre_roll": 1.5,
 *   "playback_speed": 4,
 *   "measured_width": 1920,
 *   "inactivity_periods": [...],
 *   "segment_start_timestamps": {...}
 * }
 */

const puppeteer = require('puppeteer')
const { PuppeteerScreenRecorder } = require('puppeteer-screen-recorder')

// Constants
const MAX_DIMENSION = 1920
const DEFAULT_WIDTH = 1920
const DEFAULT_HEIGHT = 1080
const RECORDING_BUFFER_SECONDS = 120
const DEFAULT_FPS = 25 // Both Playwright and ffpmeg use 25 (PAL) as a default

// Log to stderr so it doesn't interfere with JSON output
function log(...args) {
    console.error('[record-replay]', ...args)
}

// Scale dimensions if needed to fit within max width while maintaining aspect ratio
function scaleDimensionsIfNeeded(width, height, maxSize = MAX_DIMENSION) {
    if (width <= maxSize && height <= maxSize) {
        return { width, height }
    }
    let scaleFactor
    if (width > height) {
        scaleFactor = maxSize / width
        return {
            width: maxSize,
            height: Math.floor(height * scaleFactor),
        }
    } else {
        scaleFactor = maxSize / height
        return {
            width: Math.floor(width * scaleFactor),
            height: maxSize,
        }
    }
}

// Speed up playback of the video if provided by the parameters
function setupUrlForPlaybackSpeed(urlToRender, playbackSpeed) {
    const url = new URL(urlToRender)
    url.searchParams.set('playerSpeed', String(playbackSpeed))
    return url.toString()
}

// Wait for the UI and snapshots to load to be ready for the recording
async function waitForPageReady(page, urlToRender, waitForCssSelector) {
    await page.goto(urlToRender, { waitUntil: 'load', timeout: 30000 })
    try {
        await page.waitForSelector(waitForCssSelector, { visible: true, timeout: 20000 })
    } catch (e) {
        log('Selector wait timeout (continuing):', e.message)
    }
    try {
        await page.waitForSelector('.Spinner', { hidden: true, timeout: 20000 })
    } catch (e) {
        log('Spinner wait timeout (continuing):', e.message)
    }
}

// Verify the recording rendered properly by checking inactivity periods availability
// This data is set by the frontend useEffect as soon as segments load, before playback starts
// If the page failed to render (e.g., server error), this data will never be set
async function verifyInactivityPeriodsAvailable(page) {
    log('Verifying inactivity periods are available...')
    try {
        await page.waitForFunction(
            () => {
                const periods = window.__POSTHOG_INACTIVITY_PERIODS__
                return Array.isArray(periods) && periods.length > 0
            },
            { timeout: 20000 }
        )
        log('Inactivity periods verified')
    } catch (e) {
        throw new Error(
            'Inactivity periods were not available within 20s after page load. ' +
                'The session recording may not have rendered properly.'
        )
    }
}

// Wait for recording to complete while tracking segments to get real-world video timestamps
async function waitForRecordingWithSegments(page, maxWaitMs, playbackStarted) {
    const segmentStartTimestamps = {}
    let lastCounter = 0
    log('Waiting for recording with segment tracking, max wait:', maxWaitMs, 'ms')
    while (true) {
        const elapsedMs = Date.now() - playbackStarted
        const remainingMs = maxWaitMs - elapsedMs
        if (remainingMs <= 0) {
            log('Recording wait timeout reached')
            break
        }
        try {
            const handle = await page.waitForFunction(
                (lastCounterVal) => {
                    if (window.__POSTHOG_RECORDING_ENDED__) {
                        return { ended: true }
                    }
                    const counter = window.__POSTHOG_SEGMENT_COUNTER__ || 0
                    if (counter > lastCounterVal) {
                        return {
                            counter: counter,
                            segment_start_ts: window.__POSTHOG_CURRENT_SEGMENT_START_TS__,
                        }
                    }
                    return false
                },
                { timeout: remainingMs, polling: 'raf' },
                lastCounter
            )
            const result = await handle.jsonValue()
            if (result.ended) {
                log('Recording ended signal received at', elapsedMs, 'ms')
                break
            }
            const segmentStartTs = result.segment_start_ts
            const newCounter = result.counter || 0
            if (segmentStartTs !== undefined && newCounter > lastCounter) {
                const videoTime = (Date.now() - playbackStarted) / 1000
                segmentStartTimestamps[segmentStartTs] = videoTime
                log('Segment change detected:', segmentStartTs, 'at video time:', videoTime)
                lastCounter = newCounter
            }
        } catch (e) {
            // waitForFunction throws on timeout
            log('Recording wait timeout reached')
            break
        }
    }
    log('Segment tracking complete, segments tracked:', Object.keys(segmentStartTimestamps).length)
    return segmentStartTimestamps
}

// Detect inactivity periods when recording session videos
async function detectInactivityPeriods(page, playbackSpeed, segmentStartTimestamps) {
    try {
        log('Detecting inactivity periods...')
        const inactivityPeriodsRaw = await page.evaluate(() => {
            const r = window.__POSTHOG_INACTIVITY_PERIODS__
            if (!r) {
                return []
            }
            return r.map((p) => ({
                ts_from_s: Number(p.ts_from_s),
                ts_to_s: p.ts_to_s !== undefined ? Number(p.ts_to_s) : null,
                active: Boolean(p.active),
            }))
        })
        // Merge segment timestamps into periods
        if (segmentStartTimestamps && Object.keys(segmentStartTimestamps).length > 0) {
            let prevPeriodWithRecording = null
            for (const period of inactivityPeriodsRaw) {
                const tsFromS = period.ts_from_s
                if (tsFromS !== undefined && segmentStartTimestamps[tsFromS] !== undefined) {
                    const rawTimestamp = segmentStartTimestamps[tsFromS]
                    // We played video sped up, so need to multiply by playback speed to know where this moment is in the final video
                    period.recording_ts_from_s = rawTimestamp * playbackSpeed
                    // Calculate the expected duration of the current segment in actual video time
                    const tsToS = period.ts_to_s
                    if (tsToS !== undefined) {
                        const segmentDuration = tsToS - tsFromS
                        // As the final video is always slowed down to 1x, to get the end of the segment we just need to add the duration
                        period.recording_ts_to_s = period.recording_ts_from_s + segmentDuration
                    }
                    // Ensure that periods don't overlap, as the previous period should end at max at the same time as the current period starts
                    if (prevPeriodWithRecording) {
                        prevPeriodWithRecording.recording_ts_to_s = Math.min(
                            prevPeriodWithRecording.recording_ts_to_s,
                            period.recording_ts_from_s
                        )
                    }
                    prevPeriodWithRecording = period
                }
            }
        }
        log('Inactivity periods detected:', inactivityPeriodsRaw.length)
        return inactivityPeriodsRaw
    } catch (e) {
        log('Inactivity periods detection failed:', e.message)
        return null
    }
}

// Main recording function
async function main() {
    const args = process.argv.slice(2)
    if (args.length < 1) {
        console.error("Usage: node record-replay.js '<JSON_OPTIONS>'")
        process.exit(1)
    }
    let options
    try {
        // Using built-in JSON to avoid external dependencies when running in Temporal worker
        // eslint-disable-next-line no-restricted-syntax
        options = JSON.parse(args[0])
    } catch (e) {
        console.error('Failed to parse JSON options:', e.message)
        process.exit(1)
    }
    const {
        url_to_render: urlToRender,
        output_path: outputPath,
        wait_for_css_selector: waitForCssSelector,
        recording_duration: recordingDuration,
        screenshot_width: providedWidth,
        screenshot_height: providedHeight,
        playback_speed: requestedPlaybackSpeed = 1,
        headless = true,
        ffmpeg_path: ffmpegPath,
    } = options
    if (!urlToRender || !outputPath || !waitForCssSelector || !recordingDuration) {
        console.error('Missing required options: url_to_render, output_path, wait_for_css_selector, recording_duration')
        process.exit(1)
    }
    let browser
    let recorder
    try {
        log('Launching browser, headless:', headless)
        browser = await puppeteer.launch({
            headless: headless ? 'new' : false,
            // devtools: !headless, // Enable for debugging
            executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
            args: [
                // The default flag for PostHog usage of headless browsers, as they run within containers
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--use-gl=swiftshader',
                '--disable-software-rasterizer', // Seems counterintuitive, because of GL, keeping just in case (copied from image export)
                // Not applying `force-device-scale-factor`, as the original resolution should be high enough
                // `--window-size=${DEFAULT_WIDTH},${DEFAULT_HEIGHT}`, // Enable for debugging when in non-headless mode
            ],
        })
        let playbackSpeed = requestedPlaybackSpeed
        const urlWithSpeed = setupUrlForPlaybackSpeed(urlToRender, playbackSpeed)
        // Get provided dimensions or stick to default
        let width, height
        if (providedWidth && providedHeight) {
            width = providedWidth
            height = providedHeight
            log('Using provided dimensions:', width, 'x', height)
        } else {
            width = DEFAULT_WIDTH
            height = DEFAULT_HEIGHT
            log('Using default dimensions:', width, 'x', height)
        }
        // Scale if needed
        const scaled = scaleDimensionsIfNeeded(width, height)
        width = scaled.width
        height = scaled.height
        log('Final dimensions after scaling:', width, 'x', height)
        // Create page for recording
        const page = await browser.newPage()
        await page.setViewport({ width, height })
        const recordStarted = Date.now()
        // Videos are recorded at x playspeed, and will be slowed down to 1x later
        // The complication is mostly with CSS animations, as they aren't sped up by rrweb player when running at >1x playback
        const customFps = DEFAULT_FPS * playbackSpeed
        log('Custom FPS:', customFps)
        const recorderConfig = {
            followNewTab: false, // Always a single tab is recorded
            // Adjust FPS based on the playback speed, so we can speed up seamlessly later
            fps: customFps,
            ffmpeg_Path: ffmpegPath || null,
            // Render everything at full HD 16:9 to unify the output format
            videoFrame: {
                width: 1920,
                height: 1080,
            },
            videoCrf: 23, // Keeping default
            videoCodec: 'libx264',
            videoPreset: 'veryfast',
            // Adjusting bitrate to match the playback speed to keep the quality
            videoBitrate: 1000 * (0.5 * playbackSpeed),
            autopad: { color: 'black' },
            aspectRatio: '16:9',
        }
        recorder = new PuppeteerScreenRecorder(page, recorderConfig)
        // Start recording
        log('Starting recording to:', outputPath)
        await recorder.start(outputPath)
        // Navigate and wait for page ready
        await waitForPageReady(page, urlWithSpeed, waitForCssSelector)
        const readyAt = Date.now()
        await new Promise((r) => setTimeout(r, 500))
        await verifyInactivityPeriodsAvailable(page)
        // Wait for recording to complete while tracking segments, with buffer for rendering
        const maxWaitMs = Math.floor((recordingDuration / playbackSpeed) * 1000) + RECORDING_BUFFER_SECONDS * 1000
        const segmentStartTimestamps = await waitForRecordingWithSegments(page, maxWaitMs, readyAt)
        // Collect inactivity periods
        const inactivityPeriods = await detectInactivityPeriods(page, playbackSpeed, segmentStartTimestamps)
        // Stop recording
        log('Stopping recording...')
        const recordingStoppedAt = Date.now()
        await recorder.stop()
        log('Recording stopped')
        const recordingStoppingDuration = Date.now() - recordingStoppedAt
        log('Recording stopping duration:', recordingStoppingDuration, 'ms')
        // Calculate pre_roll
        const preRoll = Math.max(0, (readyAt - recordStarted) / 1000)
        await page.close()
        await browser.close()
        // Output result as JSON to stdout
        const result = {
            success: true,
            video_path: outputPath,
            pre_roll: preRoll,
            playback_speed: playbackSpeed,
            measured_width: width,
            inactivity_periods: inactivityPeriods,
            segment_start_timestamps: segmentStartTimestamps,
            custom_fps: customFps,
        }
        console.log(JSON.stringify(result))
        process.exit(0)
    } catch (error) {
        log('Error:', error.message)
        log('Stack:', error.stack)
        if (recorder) {
            try {
                await recorder.stop()
            } catch (e) {
                // Ignore cleanup errors
            }
        }
        if (browser) {
            try {
                await browser.close()
            } catch (e) {
                // Ignore cleanup errors
            }
        }
        // Output error as JSON
        const result = {
            success: false,
            error: error.message,
            stack: error.stack,
        }
        console.log(JSON.stringify(result))
        process.exit(1)
    }
}

// Only run main when executed directly (not when imported for testing)
if (require.main === module) {
    void main()
}

// Export functions for testing
module.exports = {
    scaleDimensionsIfNeeded,
    setupUrlForPlaybackSpeed,
    waitForPageReady,
    verifyInactivityPeriodsAvailable,
    waitForRecordingWithSegments,
    detectInactivityPeriods,
    // Constants
    MAX_DIMENSION,
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
}
