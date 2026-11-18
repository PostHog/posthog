export interface PlayerFrameDimensions {
    width: number
    height: number
}

export interface PlayerFrameScale {
    scale: number
    transform: string | null
}

// iPadOS 13+ reports a Mac user agent.
export function isIOS(): boolean {
    if (typeof navigator === 'undefined') {
        return false
    }
    const ua = navigator.userAgent
    return /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)
}

// Not `zoom`: WebKit propagates it into the iframe (#91417).
export function getPlayerFrameScale(parent: PlayerFrameDimensions, recorded: PlayerFrameDimensions): PlayerFrameScale {
    const scale = Math.min(parent.width / recorded.width, parent.height / recorded.height, 1)

    // Chrome clips wrongly under an identity transform.
    return { scale, transform: scale === 1 ? null : `scale(${scale})` }
}
