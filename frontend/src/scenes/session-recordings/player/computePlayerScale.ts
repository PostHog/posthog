// Cap at 0.999 instead of 1 to avoid a Chrome GPU compositing bug where
// an identity transform (scale(1)) causes the iframe layer to paint outside
// its clipping bounds, overlapping the rest of the UI.
export const MAX_PLAYER_SCALE = 0.999

/**
 * Computes the scale to apply to the rrweb wrapper, or `null` if the inputs
 * are degenerate and committing a transform would visually break the player.
 *
 * Returning `null` (rather than `0` or `NaN`) lets the caller leave the last
 * valid transform in place — important during rrweb fast-forward / skip-inactive
 * passes where `resize` can fire before the wrapper or parent are fully laid out.
 * Without this guard, a transient zero-sized parent yields `scale(0)` and the
 * iframe goes blank until something else (e.g. a window resize) triggers a recalc.
 */
export const computePlayerScale = (
    replayDimensions: { width: number; height: number } | undefined,
    parentDimensions: { width: number; height: number } | undefined
): number | null => {
    if (
        !replayDimensions ||
        !parentDimensions ||
        replayDimensions.width <= 0 ||
        replayDimensions.height <= 0 ||
        parentDimensions.width <= 0 ||
        parentDimensions.height <= 0
    ) {
        return null
    }

    const scale = Math.min(
        parentDimensions.width / replayDimensions.width,
        parentDimensions.height / replayDimensions.height,
        MAX_PLAYER_SCALE
    )

    if (!Number.isFinite(scale) || scale <= 0) {
        return null
    }

    return scale
}
