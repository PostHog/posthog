export interface PlayerFrameDimensions {
    width: number
    height: number
}

export interface PlayerFrameScale {
    // Fraction the recording is shrunk by to fit its container (1 = no shrink).
    scale: number
    // CSS `zoom` value to set on the replay wrapper, or null to clear it.
    zoom: string | null
    // CSS `transform` value to set on the replay wrapper, or null to clear it.
    transform: string | null
}

// iOS WebKit re-rasterizes composited layers at pinch-zoom scale. A decimal
// `transform: scale()` promotes the large replay iframe to such a layer and
// crashes the tab on pinch-zoom (FB13816677). iPadOS 13+ reports a Mac user
// agent, so a touch-capable Mac counts as iOS too.
export function isIOS(): boolean {
    if (typeof navigator === 'undefined') {
        return false
    }
    const ua = navigator.userAgent
    return /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)
}

// Decide how to shrink a recording to fit its container.
//
// Off iOS we scale with `transform`, which leaves the iframe at its recorded
// width, so the recorded page evaluates media queries at its real viewport.
// Safari propagates `zoom` into the iframe (CSSWG 2024 resolution), which fires
// a desktop capture's mobile breakpoints and shows the wrong layout. An identity
// transform makes Chrome paint the iframe layer outside its clip bounds, so we
// drop the transform when no shrink is needed.
//
// On iOS we keep `zoom`, which scales through layout so no oversized layer exists
// and the tab does not crash.
export function getPlayerFrameScale(
    parent: PlayerFrameDimensions,
    recorded: PlayerFrameDimensions,
    onIOS: boolean
): PlayerFrameScale {
    const scale = Math.min(parent.width / recorded.width, parent.height / recorded.height, 1)

    if (onIOS) {
        return { scale, zoom: String(scale), transform: null }
    }

    return { scale, zoom: null, transform: scale === 1 ? null : `scale(${scale})` }
}
