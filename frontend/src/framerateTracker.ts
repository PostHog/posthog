// Inspired by https://github.com/soverenio/framerate-react (MIT)

const LONG_FRAME_THRESHOLD_MS = 50
const CAPTURE_INTERVAL_MS = 30_000
const EXPECTED_FRAME_TIME_MS = 1000 / 60

interface Capturable {
    capture: (event: string, properties?: Record<string, unknown>) => void
}

/** Estimate how many frames the browser skipped during a single rAF gap, assuming 60 fps. */
export function droppedFramesForDelta(deltaMs: number): number {
    return Math.max(0, Math.round(deltaMs / EXPECTED_FRAME_TIME_MS) - 1)
}

// posthog-js can re-run its `loaded` callback whenever the SDK re-initializes. Each call used to
// spin up its own rAF loop that ran forever, so a long-lived tab accumulated trackers that all
// reported at once — collapsing measurement windows and dragging down frame health. Tracking is a
// page-global concern, so keep a single loop and hand every caller the same teardown.
let activeTeardown: (() => void) | null = null

export function startFramerateTracking(posthog: Capturable): () => void {
    if (activeTeardown) {
        return activeTeardown
    }

    let rafId: number | null = null
    let captureIntervalId: number | null = null
    let previousTimestamp: number | null = null
    let frameCount = 0
    let frameTimeSum = 0
    let shortestFrame = Infinity
    let longestFrame = 0
    let longFrameCount = 0
    let droppedFrameCount = 0
    let measurementStart = 0

    function reset(): void {
        previousTimestamp = null
        frameCount = 0
        frameTimeSum = 0
        shortestFrame = Infinity
        longestFrame = 0
        longFrameCount = 0
        droppedFrameCount = 0
        measurementStart = performance.now()
    }

    function capture(): void {
        if (frameCount === 0) {
            return
        }
        const elapsed = performance.now() - measurementStart
        posthog.capture('react_framerate', {
            avg_fps: Math.round((frameCount / elapsed) * 1000),
            avg_frame_time_ms: Math.round((frameTimeSum / frameCount) * 100) / 100,
            min_frame_time_ms: Math.round(shortestFrame * 100) / 100,
            max_frame_time_ms: Math.round(longestFrame * 100) / 100,
            long_frame_count: longFrameCount,
            dropped_frames: droppedFrameCount,
            total_frames: frameCount,
            measurement_duration_ms: Math.round(elapsed),
        })
        reset()
    }

    function onFrame(timestamp: number): void {
        if (previousTimestamp !== null) {
            const delta = timestamp - previousTimestamp
            frameCount++
            frameTimeSum += delta
            if (delta < shortestFrame) {
                shortestFrame = delta
            }
            if (delta > longestFrame) {
                longestFrame = delta
            }
            if (delta > LONG_FRAME_THRESHOLD_MS) {
                longFrameCount++
            }
            droppedFrameCount += droppedFramesForDelta(delta)
        }
        previousTimestamp = timestamp
        rafId = requestAnimationFrame(onFrame)
    }

    function start(): void {
        if (rafId !== null) {
            return
        }
        reset()
        rafId = requestAnimationFrame(onFrame)
        captureIntervalId = window.setInterval(capture, CAPTURE_INTERVAL_MS)
    }

    function stop(): void {
        if (rafId !== null) {
            cancelAnimationFrame(rafId)
            rafId = null
        }
        if (captureIntervalId !== null) {
            clearInterval(captureIntervalId)
            captureIntervalId = null
        }
    }

    function onVisibilityChange(): void {
        if (document.hidden) {
            capture()
            stop()
        } else {
            start()
        }
    }

    function teardown(): void {
        capture()
        stop()
        document.removeEventListener('visibilitychange', onVisibilityChange)
        window.removeEventListener('beforeunload', teardown)
        activeTeardown = null
    }

    document.addEventListener('visibilitychange', onVisibilityChange)

    if (!document.hidden) {
        start()
    }

    window.addEventListener('beforeunload', teardown)

    activeTeardown = teardown
    return teardown
}
