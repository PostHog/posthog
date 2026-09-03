export interface PlayerFrameDimensions {
    width: number
    height: number
}

export interface PlayerFrameScale {
    scale: number
    // null clears the property on the replay wrapper.
    zoom: string | null
    transform: string | null
}

// A decimal `transform: scale()` crashes the tab on pinch-zoom in iOS WebKit (FB13816677).
// iPadOS 13+ reports a Mac user agent; desktop Safari reports maxTouchPoints 0.
export function isIOS(): boolean {
    if (typeof navigator === 'undefined') {
        return false
    }
    const ua = navigator.userAgent
    return /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)
}

export function getPlayerFrameScale(
    parent: PlayerFrameDimensions,
    recorded: PlayerFrameDimensions,
    onIOS: boolean
): PlayerFrameScale {
    const scale = Math.min(parent.width / recorded.width, parent.height / recorded.height, 1)

    if (onIOS) {
        // `zoom` scales through layout, so no composited layer exists to re-rasterize.
        return { scale, zoom: String(scale), transform: null }
    }

    // WebKit's `zoom` shrinks the iframe's documentElement.clientWidth, firing a desktop capture's
    // mobile breakpoints. `transform` is visual only, so the recorded viewport survives. Chrome
    // paints the iframe outside its clip bounds under an identity transform, so drop it at scale 1.
    return { scale, zoom: null, transform: scale === 1 ? null : `scale(${scale})` }
}
