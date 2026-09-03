export interface PlayerFrameDimensions {
    width: number
    height: number
}

export interface PlayerFrameScale {
    scale: number
    // null clears the property on the replay wrapper.
    transform: string | null
}

// Pinch-zooming the transformed replay iframe crashes the tab in iOS WebKit (FB13816677), so the
// player blocks pinch on iOS only. iPadOS 13+ reports a Mac user agent; desktop Safari reports
// maxTouchPoints 0.
export function isIOS(): boolean {
    if (typeof navigator === 'undefined') {
        return false
    }
    const ua = navigator.userAgent
    return /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)
}

// The replay wrapper is scaled with `transform`, never `zoom`. WebKit propagates `zoom` into the
// replay iframe: the iframe's inner viewport shrinks to the zoomed size and the page inside is
// zoomed again, so a recording renders at scale squared in the top-left corner and fires its
// mobile breakpoints (#89409, #91417). `transform` is visual only, so the recorded viewport survives.
// The iOS pinch-zoom crash that motivated `zoom` is handled by `PlayerFrame--ios` in PlayerFrame.scss.
export function getPlayerFrameScale(parent: PlayerFrameDimensions, recorded: PlayerFrameDimensions): PlayerFrameScale {
    const scale = Math.min(parent.width / recorded.width, parent.height / recorded.height, 1)

    // Chrome paints the iframe outside its clip bounds under an identity transform, so drop it at scale 1.
    return { scale, transform: scale === 1 ? null : `scale(${scale})` }
}
