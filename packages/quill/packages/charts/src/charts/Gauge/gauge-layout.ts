export interface GaugeThreshold {
    /** Lower bound of the band this step colors. The lowest step also colors every value below
     *  it, so `[{ value: 0, color: green }, { value: 80, color: red }]` reads green below 80. */
    value: number
    /** Band color: hex, rgb, or `var(--…)`. The gauge resolves `var()` against the page. */
    color: string
    /** Band name for the tooltip, such as `'Healthy'`. The tooltip shows the band's range
     *  when this is omitted. */
    label?: string
}

/** The range a gauge spans. `min` equals `max` only when both were given and equal. */
export interface GaugeBounds {
    min: number
    max: number
}

export interface GaugeBand<T extends GaugeThreshold = GaugeThreshold> {
    /** Index into the sorted thresholds. */
    index: number
    threshold: T
    /** The band clipped to the gauge range. */
    from: number
    to: number
}

export interface GaugeAngles {
    /** Canvas radians: 0 is 3 o'clock and angles grow clockwise. */
    start: number
    end: number
    sweep: number
}

export interface GaugeLayout {
    cx: number
    cy: number
    angles: GaugeAngles
    /** Centerline radius of the track and the value arc. */
    radius: number
    thickness: number
    innerRadius: number
    /** Outer edge of the outermost ring: the threshold bands when shown, else the track. */
    outerRadius: number
    /** Centerline radius of the threshold band ring, 0 when the ring is hidden. */
    bandRadius: number
    bandThickness: number
    /** Lowest y the rings paint, where the min and max labels hang from. */
    bottom: number
}

export const DEFAULT_GAUGE_SWEEP = 240
export const MIN_GAUGE_SWEEP = 180
export const MAX_GAUGE_SWEEP = 360
export const DEFAULT_GAUGE_THICKNESS = 0.15

// Ring proportions as fractions of the outer radius, so a gauge keeps its look from 80px to 400px.
const BAND_RING_THICKNESS = 0.055
const BAND_RING_GAP = 0.04
const MIN_THICKNESS = 0.04
const MAX_THICKNESS = 0.5
// Proportional rings turn heavy on a large gauge, so they stop growing past these sizes.
const MAX_THICKNESS_PX = 28
const MAX_BAND_PX = 8
const MAX_BAND_GAP_PX = 6

const isFiniteNumber = (n: number | null | undefined): n is number => typeof n === 'number' && Number.isFinite(n)

const clamp = (n: number, lo: number, hi: number): number => Math.min(Math.max(n, lo), hi)

/** Thresholds in ascending `value` order, without non-finite steps. Input order does not matter. */
export function sortThresholds<T extends GaugeThreshold>(thresholds: readonly T[] | undefined): T[] {
    return (thresholds ?? []).filter((t) => isFiniteNumber(t.value)).sort((a, b) => a.value - b.value)
}

export interface ResolveGaugeBoundsInput {
    /** The value the gauge shows. `null` does not move the range. */
    value: number | null
    min?: number | null
    max?: number | null
    thresholds?: readonly GaugeThreshold[]
    /** A target marker value. An inferred range grows to contain it. */
    target?: number | null
}

/** The gauge range. An explicit `min` or `max` always wins. A missing `min` is the lowest threshold
 *  (else 0), lowered to 0, or to the value when it is negative, when the value or target sits under
 *  it. A missing `max` is the highest threshold (else the larger of `min + 1` and 0), raised to contain
 *  the value and the target, because a threshold ladder that stops short of the value is a color
 *  scale, not the range. The min and max labels then agree with where the arc ends. */
export function resolveGaugeBounds({ value, min, max, thresholds, target }: ResolveGaugeBoundsInput): GaugeBounds {
    const sorted = sortThresholds(thresholds)
    const contained = [value, target].filter(isFiniteNumber)
    const explicitMin = isFiniteNumber(min) ? min : undefined
    const explicitMax = isFiniteNumber(max) ? max : undefined

    if (explicitMin !== undefined && explicitMax !== undefined) {
        return explicitMin <= explicitMax
            ? { min: explicitMin, max: explicitMax }
            : { min: explicitMax, max: explicitMin }
    }

    // A value under the lowest threshold widens the range to 0 rather than to the value itself, so a
    // healthy value beneath an alert ladder does not sit at the empty end of the arc.
    const base = sorted.length ? sorted[0].value : 0
    const lowest = Math.min(base, ...contained)
    let lo = explicitMin ?? (lowest < base ? Math.min(0, lowest) : base)
    if (explicitMax !== undefined && lo >= explicitMax) {
        lo = explicitMax - 1
    }
    if (explicitMax !== undefined) {
        return { min: lo, max: explicitMax }
    }
    const hi = Math.max(sorted.length ? sorted[sorted.length - 1].value : Math.max(lo + 1, 0), ...contained)
    return { min: lo, max: hi > lo ? hi : lo + 1 }
}

/** Where `value` sits in the range, from 0 to 1. Out-of-range values clamp to the nearest end. When
 *  `min` equals `max` the gauge reads empty below that value and full at or above it. */
export function gaugeFraction(value: number | null, { min, max }: GaugeBounds): number {
    if (!isFiniteNumber(value)) {
        return 0
    }
    if (max <= min) {
        return value >= max ? 1 : 0
    }
    return clamp((value - min) / (max - min), 0, 1)
}

/** Index of the sorted threshold that colors `value`: the last step at or below it, or the lowest
 *  step when the value is below every step. -1 when there are no thresholds or no value. */
export function thresholdIndexAt(value: number | null, sorted: readonly GaugeThreshold[]): number {
    if (!isFiniteNumber(value) || sorted.length === 0) {
        return -1
    }
    let index = 0
    for (let i = 1; i < sorted.length; i++) {
        if (value >= sorted[i].value) {
            index = i
        } else {
            break
        }
    }
    return index
}

/** The visible part of each threshold band, clipped to the range. Bands outside the range or with
 *  no width are dropped. */
export function thresholdBands<T extends GaugeThreshold>(sorted: readonly T[], bounds: GaugeBounds): GaugeBand<T>[] {
    const bands: GaugeBand<T>[] = []
    for (let i = 0; i < sorted.length; i++) {
        const from = i === 0 ? bounds.min : Math.max(sorted[i].value, bounds.min)
        const to = i + 1 < sorted.length ? Math.min(sorted[i + 1].value, bounds.max) : bounds.max
        if (to > from) {
            bands.push({ index: i, threshold: sorted[i], from, to })
        }
    }
    return bands
}

/** Clamp a sweep in degrees to the supported range. Below 180° the inner text no longer fits inside
 *  the arc, so narrower sweeps are not supported. */
export function clampGaugeSweep(sweepDegrees: number | undefined): number {
    return isFiniteNumber(sweepDegrees) ? clamp(sweepDegrees, MIN_GAUGE_SWEEP, MAX_GAUGE_SWEEP) : DEFAULT_GAUGE_SWEEP
}

/** Start and end angles of an arc of `sweepDegrees`, centered on 12 o'clock so the opening faces down.
 *  A full ring starts at 12 o'clock instead, like a progress ring. */
export function gaugeAngles(sweepDegrees: number): GaugeAngles {
    const sweep = (clampGaugeSweep(sweepDegrees) * Math.PI) / 180
    const start = sweep >= 2 * Math.PI ? -Math.PI / 2 : -Math.PI / 2 - sweep / 2
    return { start, end: start + sweep, sweep }
}

export function fractionToAngle(fraction: number, angles: GaugeAngles): number {
    return angles.start + clamp(fraction, 0, 1) * angles.sweep
}

interface Box {
    minX: number
    maxX: number
    minY: number
    maxY: number
}

function angleInArc(angle: number, angles: GaugeAngles): boolean {
    const turn = 2 * Math.PI
    const offset = (((angle - angles.start) % turn) + turn) % turn
    return offset <= angles.sweep + 1e-9
}

/** Bounding box of a ring sector around the origin. */
export function ringSectorBox(angles: GaugeAngles, innerRadius: number, outerRadius: number): Box {
    const points: [number, number][] = []
    for (const angle of [angles.start, angles.end]) {
        for (const r of [innerRadius, outerRadius]) {
            points.push([Math.cos(angle) * r, Math.sin(angle) * r])
        }
    }
    for (let k = 0; k < 4; k++) {
        const angle = (k * Math.PI) / 2
        if (angles.sweep >= 2 * Math.PI - 1e-9 || angleInArc(angle, angles)) {
            points.push([Math.cos(angle) * outerRadius, Math.sin(angle) * outerRadius])
        }
    }
    return {
        minX: Math.min(...points.map((p) => p[0])),
        maxX: Math.max(...points.map((p) => p[0])),
        minY: Math.min(...points.map((p) => p[1])),
        maxY: Math.max(...points.map((p) => p[1])),
    }
}

export interface ComputeGaugeLayoutInput {
    width: number
    height: number
    sweep: number
    /** Arc thickness as a fraction of the outer radius. */
    thickness: number
    showBands: boolean
    /** Pixels reserved under the rings for the min and max labels. */
    footer: number
    padding: number
    /** Leave room past the outer ring for a target tick. */
    hasTarget?: boolean
}

export interface TargetTickSize {
    /** How far the tick runs past the inner and outer ring edges. */
    overhang: number
    width: number
    /** Width of the gap erased around the tick on each side. */
    gap: number
}

export function targetTickSize(thickness: number): TargetTickSize {
    const width = Math.max(2, thickness * 0.16)
    return { overhang: Math.max(2, thickness * 0.18), width, gap: Math.max(1.5, width * 0.6) }
}

/** Fit the rings into the box, centered, at the largest radius that leaves room for the footer and,
 *  with a target, for the tick's reach past the outer ring. */
export function computeGaugeLayout(input: ComputeGaugeLayoutInput): GaugeLayout {
    const layout = fitGaugeLayout(input)
    if (!input.hasTarget) {
        return layout
    }
    const { overhang, width, gap } = targetTickSize(layout.thickness)
    return fitGaugeLayout({ ...input, padding: input.padding + overhang + width / 2 + gap })
}

function fitGaugeLayout({
    width,
    height,
    sweep,
    thickness,
    showBands,
    footer,
    padding,
}: ComputeGaugeLayoutInput): GaugeLayout {
    const angles = gaugeAngles(sweep)
    const t = isFiniteNumber(thickness) ? clamp(thickness, MIN_THICKNESS, MAX_THICKNESS) : DEFAULT_GAUGE_THICKNESS
    const trackOuter = showBands ? 1 - BAND_RING_THICKNESS - BAND_RING_GAP : 1
    const unitBox = ringSectorBox(angles, trackOuter - t, 1)
    const unitWidth = unitBox.maxX - unitBox.minX
    const unitHeight = unitBox.maxY - unitBox.minY

    const availableWidth = Math.max(0, width - 2 * padding)
    const availableHeight = Math.max(0, height - 2 * padding - footer)
    const outerRadius = Math.max(0, Math.min(availableWidth / unitWidth, availableHeight / unitHeight))

    const contentHeight = unitHeight * outerRadius + footer
    const top = padding + (Math.max(0, height - 2 * padding) - contentHeight) / 2
    const left = padding + (availableWidth - unitWidth * outerRadius) / 2
    const cx = left - unitBox.minX * outerRadius
    const cy = top - unitBox.minY * outerRadius

    const bandPx = showBands ? Math.min(BAND_RING_THICKNESS * outerRadius, MAX_BAND_PX) : 0
    const gapPx = showBands ? Math.min(BAND_RING_GAP * outerRadius, MAX_BAND_GAP_PX) : 0
    const trackOuterPx = outerRadius - bandPx - gapPx
    const px = Math.min(t * outerRadius, MAX_THICKNESS_PX)
    return {
        cx,
        cy,
        angles,
        radius: trackOuterPx - px / 2,
        thickness: px,
        innerRadius: trackOuterPx - px,
        outerRadius,
        bandRadius: showBands ? outerRadius - bandPx / 2 : 0,
        bandThickness: bandPx,
        bottom: cy + unitBox.maxY * outerRadius,
    }
}

/** Angle by which a round cap of `thickness` reaches past an arc end, so arcs can be shortened by
 *  it and still end on the exact value angle. */
export function roundCapInset(radius: number, thickness: number): number {
    if (radius <= 0) {
        return 0
    }
    return Math.asin(clamp(thickness / 2 / radius, 0, 1))
}

/** Whether a point (relative to the chart wrapper) is over the gauge. */
export function isOverGauge(layout: GaugeLayout, x: number, y: number): boolean {
    return Math.hypot(x - layout.cx, y - layout.cy) <= layout.outerRadius + 4
}

export interface GaugeTextBlockInput {
    layout: GaugeLayout
    /** Measures `text` in px for a CSS `font` shorthand. */
    measure: (text: string, font: string) => number
    fontFamily: string
    valueText: string
    labelText: string | null
}

export interface GaugeTextLine {
    text: string
    /** Center x and center y, relative to the chart wrapper. */
    x: number
    y: number
    fontSize: number
    maxWidth: number
}

export interface GaugeTextBlock {
    value: GaugeTextLine
    label: GaugeTextLine | null
}

export const GAUGE_VALUE_FONT_WEIGHT = 600
const MAX_VALUE_FONT = 64
const MIN_VALUE_FONT = 9
const MIN_LABEL_FONT = 9
const MAX_LABEL_FONT = 14
const LABEL_LINE_HEIGHT = 1.25
const TEXT_GAP_RATIO = 0.12
// Glyph widths vary across fonts and the measure can use a different fallback font than the page,
// so lines stop short of the chord.
const CHORD_FILL = 0.86
const FIT_SAFETY = 1.04

function chordWidth(radius: number, dy: number): number {
    return dy >= radius ? 0 : 2 * Math.sqrt(radius * radius - dy * dy)
}

/** Size and place the value and the label inside the arc. The value shrinks until it fits the chord
 *  of the inner circle at its line, and the label drops out when the two no longer fit together. */
export function layoutGaugeText({
    layout,
    measure,
    fontFamily,
    valueText,
    labelText,
}: GaugeTextBlockInput): GaugeTextBlock {
    const { cx, cy, innerRadius, angles } = layout
    // The inner edge of the arc ends dips below the center on sweeps past 180°. The text block
    // stays above those ends so the opening stays clear.
    const endDip = Math.max(0, Math.sin((angles.sweep - Math.PI) / 2)) * innerRadius
    const floorY = angles.sweep >= 2 * Math.PI - 1e-9 ? cy + innerRadius * 0.7 : cy + endDip * 0.9

    const place = (withLabel: boolean): GaugeTextBlock => {
        const initialFont = clamp(innerRadius * 0.46, MIN_VALUE_FONT, MAX_VALUE_FONT)
        let valueFont = initialFont
        const labelFont = withLabel ? clamp(valueFont * 0.3, MIN_LABEL_FONT, MAX_LABEL_FONT) : 0
        const gap = withLabel ? valueFont * TEXT_GAP_RATIO : 0
        const labelHeight = labelFont * LABEL_LINE_HEIGHT

        const blockFor = (font: number): { valueY: number; labelY: number; height: number } => {
            const height = font + gap + labelHeight
            let centerY = cy
            if (centerY + height / 2 > floorY) {
                centerY = floorY - height / 2
            }
            const blockTop = centerY - height / 2
            return { valueY: blockTop + font / 2, labelY: blockTop + font + gap + labelHeight / 2, height }
        }

        const valueWidthAt = (font: number): number => {
            const { valueY } = blockFor(font)
            const dy = Math.max(Math.abs(valueY - font / 2 - cy), Math.abs(valueY + font / 2 - cy))
            return chordWidth(innerRadius, dy) * CHORD_FILL
        }

        const measured = measure(valueText, `${GAUGE_VALUE_FONT_WEIGHT} ${initialFont}px ${fontFamily}`)
        // Shrinking the font also moves the line, which changes the chord, so iterate a few times.
        for (let i = 0; i < 4 && measured > 0; i++) {
            const fit = valueWidthAt(valueFont)
            const width = (measured * valueFont) / initialFont
            if (width * FIT_SAFETY <= fit) {
                break
            }
            valueFont = Math.max(MIN_VALUE_FONT, (valueFont * fit) / (width * FIT_SAFETY))
        }

        const { valueY, labelY } = blockFor(valueFont)
        const value: GaugeTextLine = {
            text: valueText,
            x: cx,
            y: valueY,
            fontSize: valueFont,
            maxWidth: valueWidthAt(valueFont),
        }
        if (!withLabel || labelText === null) {
            return { value, label: null }
        }
        const dy = Math.max(Math.abs(labelY - labelHeight / 2 - cy), Math.abs(labelY + labelHeight / 2 - cy))
        return {
            value,
            label: {
                text: labelText,
                x: cx,
                y: labelY,
                fontSize: labelFont,
                maxWidth: chordWidth(innerRadius, dy) * CHORD_FILL,
            },
        }
    }

    if (labelText) {
        const block = place(true)
        const top = block.value.y - block.value.fontSize / 2
        const fitsAbove = top >= cy - innerRadius * 0.95
        if (fitsAbove && block.label && block.label.maxWidth >= MIN_LABEL_FONT * 3) {
            return block
        }
    }
    return place(false)
}
