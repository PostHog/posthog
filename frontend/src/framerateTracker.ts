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

export function startFramerateTracking(posthog: Capturable): void {
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

    document.addEventListener('visibilitychange', onVisibilityChange)

    if (!document.hidden) {
        start()
    }

    window.addEventListener('beforeunload', () => {
        capture()
        stop()
        document.removeEventListener('visibilitychange', onVisibilityChange)
    })
}
