/**
 * Node.js video recording script using Puppeteer + puppeteer-screen-recorder
 * Input JSON:
 * {
 *   "url_to_render": "https://...",
 *   "output_path": "/tmp/video.webm",
 *   "wait_for_css_selector": ".replayer-wrapper",
 *   "recording_duration": 60,
 *   "screenshot_width": 1400,      // optional
 *   "screenshot_height": 600,      // optional
 *   "playback_speed": 1,           // optional, default 1
 *   "headless": true               // optional, default true
 * }
 *
 * Output JSON (to stdout):
 * {
 *   "success": true,
 *   "video_path": "/tmp/video.webm",
 *   "pre_roll": 1.5,
 *   "playback_speed": 4,
 *   "measured_width": 1400,
 *   "inactivity_periods": [...],
 *   "segment_start_timestamps": {...}
 * }
 */

const puppeteer = require('puppeteer')
const { PuppeteerScreenRecorder } = require('puppeteer-screen-recorder')
const path = require('path')

// Constats, replicated from Playwright flow
const HEIGHT_OFFSET = 85
const PLAYBACK_SPEED_MULTIPLIER = 4
const MAX_DIMENSION = 1400
const DEFAULT_WIDTH = 1400
const DEFAULT_HEIGHT = 600
const RECORDING_BUFFER_SECONDS = 120

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
function ensurePlaybackSpeed(urlToRender, playbackSpeed) {
    const url = new URL(urlToRender)
    url.searchParams.set('playerSpeed', String(playbackSpeed))
    return url.toString()
}

// Wait for the UI and snapshots to load to be ready for the recording
async function waitForPageReady(page, urlToRender, waitForCssSelector) {
    try {
        await page.goto(urlToRender, { waitUntil: 'load', timeout: 30000 })
    } catch (e) {
        log('Navigation timeout (continuing):', e.message)
    }
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

// Detect the recording resolution from the UI
async function detectRecordingResolution(browser, urlToRender, waitForCssSelector, defaultWidth, defaultHeight) {
    log('Starting resolution detection...')
    const page = await browser.newPage()
    // TODO: Check the logic here
    await page.setViewport({ width: defaultWidth, height: defaultHeight })
    try {
        await waitForPageReady(page, urlToRender, waitForCssSelector)
        const resolution = await page.evaluate(() => {
            return new Promise((resolve) => {
                const checkResolution = () => {
                    const r = window.__POSTHOG_RESOLUTION__
                    if (r) {
                        const w = Number(r.width)
                        const h = Number(r.height)
                        if (w > 0 && h > 0) {
                            resolve({ width: w, height: h })
                            return
                        }
                    }
                    setTimeout(checkResolution, 100)
                }
                checkResolution()
                // Timeout after 15s
                setTimeout(() => resolve(null), 15000)
            })
        })
        if (resolution) {
            log('Resolution detected:', resolution)
            return resolution
        }
    } catch (e) {
        log('Resolution detection failed:', e.message)
    } finally {
        await page.close()
    }
    log('Using default resolution')
    return { width: defaultWidth, height: defaultHeight }
}

// Wait for recording to complete while tracking segments to get real-world video timestamps
async function waitForRecordingWithSegments(page, maxWaitMs, playbackStarted) {
    const segmentStartTimestamps = {}
    let lastCounter = 0
    log('Waiting for recording with segment tracking, max wait:', maxWaitMs, 'ms')
    while (true) {
        const elapsedMs = Date.now() - playbackStarted
        if (elapsedMs >= maxWaitMs) {
            log('Recording wait timeout reached')
            break
        }
        try {
            const remainingMs = maxWaitMs - elapsedMs
            const result = await page.evaluate((lastCounterVal) => {
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
                return null
            }, lastCounter)
            if (result === null) {
                await new Promise((r) => setTimeout(r, Math.min(1000, remainingMs)))
                continue
            }
            if (result.ended) {
                log('Recording ended signal received')
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
            // Continue waiting despite errors
            await new Promise((r) => setTimeout(r, 100))
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
            for (const period of inactivityPeriodsRaw) {
                const tsFromS = period.ts_from_s
                if (tsFromS !== undefined && segmentStartTimestamps[tsFromS] !== undefined) {
                    const rawTimestamp = segmentStartTimestamps[tsFromS]
                    period.recording_ts_from_s = Math.round(rawTimestamp * playbackSpeed)
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
    } = options
    if (!urlToRender || !outputPath || !waitForCssSelector || !recordingDuration) {
        console.error('Missing required options: url_to_render, output_path, wait_for_css_selector, recording_duration')
        process.exit(1)
    }
    const ext = path.extname(outputPath).toLowerCase()
    let browser
    let recorder
    try {
        log('Launching browser, headless:', headless)
        browser = await puppeteer.launch({
            headless: headless ? 'new' : false,
            devtools: !headless,
            executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
            args: [
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--use-gl=swiftshader',
                '--disable-software-rasterizer',
                '--force-device-scale-factor=2',
            ],
        })
        // Detect or use provided dimensions
        let width, height
        if (providedWidth && providedHeight) {
            width = providedWidth
            height = providedHeight
            log('Using provided dimensions:', width, 'x', height)
        } else {
            const detected = await detectRecordingResolution(
                browser,
                urlToRender,
                waitForCssSelector,
                DEFAULT_WIDTH,
                DEFAULT_HEIGHT
            )
            width = detected.width
            height = detected.height
            log('Using detected dimensions:', width, 'x', height)
        }
        // Scale if needed
        const scaled = scaleDimensionsIfNeeded(width, height)
        width = scaled.width
        height = scaled.height
        log('Final dimensions after scaling:', width, 'x', height)
        // Determine playback speed
        let playbackSpeed = requestedPlaybackSpeed
        if (['.mp4', '.webm'].includes(ext) && recordingDuration > 5 && requestedPlaybackSpeed === 1) {
            playbackSpeed = PLAYBACK_SPEED_MULTIPLIER
        }
        log('Playback speed:', playbackSpeed)
        // Create page for recording
        const page = await browser.newPage()
        await page.setViewport({ width, height })
        const recordStarted = Date.now()
        // Configure screen recorder
        const customFps = 30 * playbackSpeed // TODO: Decide if it's not too much
        const recorderConfig = {
            followNewTab: false, // Always a single tab is recorded
            // Adjust FPS based on the playback speed, so we can speed up seamlessly later
            fps: customFps,
            ffmpeg_Path: null, // TODO: Check if it picks the system one, or installs it instead
            videoFrame: {
                width,
                height,
            },
            videoCrf: 23, // Keeping default
            videoCodec: 'libvpx-vp9', // Using V9, think if it makes sense to record the original in lossless mode
            // videoPreset should not be used as we use V9 codec
            // Adjusting bitrate to match the playback speed to keep the quality
            videoBitrate: 1000 * (0.5 * playbackSpeed),
            // No autopad
            // Keep to two aspect ratios for the time being
            aspectRatio: width > height ? '16:9' : '9:16', // TODO: Find a better way to decide it
        }
        recorder = new PuppeteerScreenRecorder(page, recorderConfig)
        // Start recording
        log('Starting recording to:', outputPath)
        await recorder.start(outputPath)
        // Navigate and wait for page ready
        const urlWithSpeed = ensurePlaybackSpeed(urlToRender, playbackSpeed)
        await waitForPageReady(page, urlWithSpeed, waitForCssSelector)
        // Adjust viewport based on content
        let measuredWidth = null
        try {
            const dimensions = await page.evaluate(() => {
                const replayer = document.querySelector('.replayer-wrapper')
                if (replayer) {
                    const rect = replayer.getBoundingClientRect()
                    return {
                        height: Math.max(rect.height, document.body.scrollHeight),
                        width: replayer.offsetWidth || 0,
                    }
                }
                const table = document.querySelector('table')
                return {
                    height: document.body.scrollHeight,
                    width: table ? Math.floor((table.offsetWidth || 0) * 1.5) : 0,
                }
            })
            const finalHeight = dimensions.height
            const widthCandidate = dimensions.width || width
            measuredWidth = Math.max(width, Math.min(1800, Math.floor(widthCandidate)))
            await page.setViewport({
                width: measuredWidth,
                height: Math.floor(finalHeight) + HEIGHT_OFFSET,
            })
            log('Viewport resized to:', measuredWidth, 'x', Math.floor(finalHeight) + HEIGHT_OFFSET)
        } catch (e) {
            log('Viewport resize failed:', e.message)
        }
        const readyAt = Date.now()
        await new Promise((r) => setTimeout(r, 500))
        // Wait for recording to complete while tracking segments, with buffer for rendering
        const maxWaitMs = Math.floor((recordingDuration / playbackSpeed) * 1000) + RECORDING_BUFFER_SECONDS * 1000
        const segmentStartTimestamps = await waitForRecordingWithSegments(page, maxWaitMs, readyAt)
        // Collect inactivity periods
        const inactivityPeriods = await detectInactivityPeriods(page, playbackSpeed, segmentStartTimestamps)
        // Stop recording
        log('Stopping recording...')
        await recorder.stop()
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
            measured_width: measuredWidth,
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
    ensurePlaybackSpeed,
    waitForPageReady,
    detectRecordingResolution,
    waitForRecordingWithSegments,
    detectInactivityPeriods,
    // Constants
    HEIGHT_OFFSET,
    PLAYBACK_SPEED_MULTIPLIER,
    MAX_DIMENSION,
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
}
