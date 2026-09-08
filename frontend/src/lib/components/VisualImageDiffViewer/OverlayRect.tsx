// A one-row band is a zero-area rect once the SVG scales it down. The stroke
// is non-scaling so it still draws, but the fill needs a floor to be visible.
const MIN_OVERLAY_SIDE_PX = 3

interface OverlayRectProps {
    x: number
    y: number
    width: number
    height: number
    fill: string
    stroke: string
    strokeWidth: number
    strokeDasharray?: string
    opacity?: number
    onHover?: (index: number | null) => void
    index?: number
}

/** One overlay rectangle, clamped so a one-pixel side still has an area to fill. */
export function OverlayRect({
    x,
    y,
    width,
    height,
    fill,
    stroke,
    strokeWidth,
    strokeDasharray,
    opacity,
    onHover,
    index,
}: OverlayRectProps): JSX.Element {
    const hoverable = !!onHover && index !== undefined
    return (
        <rect
            x={x}
            y={y}
            width={Math.max(width, MIN_OVERLAY_SIDE_PX)}
            height={Math.max(height, MIN_OVERLAY_SIDE_PX)}
            fill={fill}
            stroke={stroke}
            strokeWidth={strokeWidth}
            strokeDasharray={strokeDasharray}
            opacity={opacity}
            vectorEffect="non-scaling-stroke"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                pointerEvents: hoverable ? 'auto' : 'none',
                cursor: hoverable ? 'pointer' : undefined,
            }}
            onMouseEnter={hoverable ? () => onHover(index) : undefined}
            onMouseLeave={hoverable ? () => onHover(null) : undefined}
        />
    )
}
