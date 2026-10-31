/** A value from which the gauge takes this color. */
export interface GaugeThreshold {
    value: number
    color: string
}

/** Where `value` sits between `min` and `max`, clamped to 0..1. */
export function gaugeFraction(value: number, min: number, max: number): number {
    if (!(max > min)) {
        return 0
    }
    return Math.max(0, Math.min(1, (value - min) / (max - min)))
}

/** The color of the highest threshold at or below `value`, or `fallback` below all of them. */
export function thresholdColor(value: number, thresholds: readonly GaugeThreshold[], fallback: string): string {
    let color = fallback
    let best = -Infinity
    for (const t of thresholds) {
        if (t.value <= value && t.value >= best) {
            best = t.value
            color = t.color
        }
    }
    return color
}

/** The threshold ranges inside `[min, max]` as fractions of the gauge, for the radial markers. The
 *  range below the first threshold takes `fallback`. */
export function thresholdSegments(
    thresholds: readonly GaugeThreshold[],
    min: number,
    max: number,
    fallback: string
): { from: number; to: number; color: string }[] {
    const sorted = [...thresholds].sort((a, b) => a.value - b.value)
    const starts = [{ value: -Infinity, color: fallback }, ...sorted]
    return starts
        .map((t, i) => ({
            from: gaugeFraction(t.value, min, max),
            to: gaugeFraction(starts[i + 1]?.value ?? Infinity, min, max),
            color: t.color,
        }))
        .filter((segment) => segment.to > segment.from)
}

/** Radial gauge sweep: 240 degrees, open at the bottom. Angles run clockwise from the +x axis in
 *  SVG's y-down space, so 150 is bottom-left and 390 is bottom-right. */
const START_ANGLE = 150
const SWEEP = 240

/** SVG path for the arc of a radial gauge between two fractions of its sweep. */
export function gaugeArcPath(cx: number, cy: number, radius: number, from: number, to: number): string {
    const point = (fraction: number): string => {
        const angle = ((START_ANGLE + SWEEP * fraction) * Math.PI) / 180
        return `${cx + radius * Math.cos(angle)} ${cy + radius * Math.sin(angle)}`
    }
    const largeArc = SWEEP * (to - from) > 180 ? 1 : 0
    return `M ${point(from)} A ${radius} ${radius} 0 ${largeArc} 1 ${point(to)}`
}
