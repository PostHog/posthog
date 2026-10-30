import {
    computeGaugeLayout,
    gaugeAngles,
    gaugeFraction,
    isOverGauge,
    layoutGaugeText,
    resolveGaugeBounds,
    ringSectorBox,
    targetTickSize,
    thresholdBands,
    thresholdIndexAt,
} from './gauge-layout'
import type { GaugeThreshold, ResolveGaugeBoundsInput } from './gauge-layout'

const steps = (...values: number[]): GaugeThreshold[] => values.map((value, i) => ({ value, color: `c${i}` }))

const deg = (radians: number): number => Math.round((radians * 180) / Math.PI)

describe('gauge layout', () => {
    it.each<[string, ResolveGaugeBoundsInput, { min: number; max: number }]>([
        [
            'explicit min and max win over value and thresholds',
            { value: 500, min: 0, max: 100, thresholds: steps(50, 900) },
            { min: 0, max: 100 },
        ],
        ['inverted explicit bounds are swapped', { value: 5, min: 10, max: 0 }, { min: 0, max: 10 }],
        ['equal explicit bounds stay degenerate', { value: 5, min: 5, max: 5 }, { min: 5, max: 5 }],
        [
            'thresholds span the range when no bounds are given',
            { value: 60, thresholds: steps(90, 0, 50) },
            { min: 0, max: 90 },
        ],
        [
            'a value under the lowest threshold widens the range to 0, not to the value',
            { value: 30, thresholds: steps(70, 90) },
            { min: 0, max: 90 },
        ],
        [
            'an inferred max grows to contain a value past the last threshold',
            { value: 150, thresholds: steps(50, 90) },
            { min: 50, max: 150 },
        ],
        ['an inferred min drops to contain a negative value', { value: -20 }, { min: -20, max: 0 }],
        ['a value alone falls back to 0 through min + 1', { value: 0.4 }, { min: 0, max: 1 }],
        [
            'a fractional threshold ladder is not stretched to min + 1',
            { value: 0.3, thresholds: steps(0, 0.5) },
            { min: 0, max: 0.5 },
        ],
        [
            'an inferred max grows to contain the target',
            { value: 10, max: undefined, min: 0, target: 120 },
            { min: 0, max: 120 },
        ],
        ['an inferred min never crosses an explicit max', { value: null, max: -5 }, { min: -6, max: -5 }],
        ['a null value is ignored', { value: null }, { min: 0, max: 1 }],
    ])('resolves bounds: %s', (_name, input, expected) => {
        expect(resolveGaugeBounds(input)).toEqual(expected)
    })

    it.each([
        ['inside the range', 25, { min: 0, max: 100 }, 0.25],
        ['below min clamps to empty', -10, { min: 0, max: 100 }, 0],
        ['above max clamps to full', 140, { min: 0, max: 100 }, 1],
        ['a negative range', 0, { min: -50, max: 50 }, 0.5],
        ['min equal to max is empty below the value', 4, { min: 5, max: 5 }, 0],
        ['min equal to max is full at the value', 5, { min: 5, max: 5 }, 1],
        ['null is empty', null, { min: 0, max: 100 }, 0],
    ])('maps a value to a fraction: %s', (_name, value, bounds, expected) => {
        expect(gaugeFraction(value, bounds)).toBeCloseTo(expected)
    })

    it.each([
        ['below every step takes the lowest step', 10, 0],
        ['exactly on a step takes that step', 50, 1],
        ['between steps takes the lower one', 75, 1],
        ['past the last step takes the last one', 1000, 2],
        ['no value has no step', null, -1],
    ])('finds the threshold for a value: %s', (_name, value, expected) => {
        expect(thresholdIndexAt(value, steps(20, 50, 90))).toBe(expected)
    })

    it('clips threshold bands to the range and drops the ones outside it', () => {
        const bands = thresholdBands(steps(0, 70, 90, 200), { min: 0, max: 100 })
        expect(bands.map(({ index, from, to }) => ({ index, from, to }))).toEqual([
            { index: 0, from: 0, to: 70 },
            { index: 1, from: 70, to: 90 },
            { index: 2, from: 90, to: 100 },
        ])
    })

    it.each([
        ['the default 240° opens downward', 240, [-210, 30]],
        ['a half circle spans 9 to 3 o’clock', 180, [-180, 0]],
        ['a full ring starts at 12 o’clock', 360, [-90, 270]],
        ['a sweep below 180° clamps to a half circle', 90, [-180, 0]],
        ['a sweep past 360° clamps to a full ring', 720, [-90, 270]],
    ])('places the arc: %s', (_name, sweep, [start, end]) => {
        const angles = gaugeAngles(sweep)
        expect([deg(angles.start), deg(angles.end)]).toEqual([start, end])
    })

    it.each([
        [80, 70, 240, false],
        [400, 300, 240, false],
        [400, 120, 240, false],
        [140, 400, 180, false],
        [300, 300, 360, false],
        [1000, 160, 300, false],
        [320, 240, 240, true],
        [140, 400, 180, true],
    ])(
        'keeps a %ipx by %ipx, %i° gauge (target: %s) inside its box with room for the footer',
        (width, height, sweep, hasTarget) => {
            const footer = 14
            const padding = 4
            const layout = computeGaugeLayout({
                width,
                height,
                sweep,
                thickness: 0.15,
                showBands: true,
                footer,
                padding,
                hasTarget,
            })
            const tick = targetTickSize(layout.thickness)
            const reach = hasTarget ? tick.overhang + tick.width / 2 + tick.gap : 0
            const box = ringSectorBox(layout.angles, layout.innerRadius, layout.outerRadius)
            const left = layout.cx + box.minX - reach
            const right = layout.cx + box.maxX + reach
            const top = layout.cy + box.minY - reach
            expect(left).toBeGreaterThanOrEqual(padding - 1e-6)
            expect(right).toBeLessThanOrEqual(width - padding + 1e-6)
            expect(top).toBeGreaterThanOrEqual(padding - 1e-6)
            expect(layout.bottom + footer).toBeLessThanOrEqual(height - padding + 1e-6)
            expect(Math.abs(left - (width - right))).toBeLessThan(1e-6)
        }
    )

    it('shrinks a long value until it fits the inner chord, and drops the label in a tiny gauge', () => {
        const measure = (text: string, font: string): number =>
            text.length * Number(/(\d+(\.\d+)?)px/.exec(font)?.[1]) * 0.6
        const layout = computeGaugeLayout({
            width: 400,
            height: 300,
            sweep: 240,
            thickness: 0.15,
            showBands: false,
            footer: 0,
            padding: 4,
        })
        const short = layoutGaugeText({ layout, measure, fontFamily: 'x', valueText: '42%', labelText: 'CPU' })
        const long = layoutGaugeText({
            layout,
            measure,
            fontFamily: 'x',
            valueText: '3,141,592.65 req/s',
            labelText: 'CPU',
        })
        expect(long.value.fontSize).toBeLessThan(short.value.fontSize)
        expect(measure(long.value.text, `${long.value.fontSize}px x`)).toBeLessThanOrEqual(long.value.maxWidth)
        expect(short.label?.text).toBe('CPU')

        const tiny = computeGaugeLayout({
            width: 40,
            height: 36,
            sweep: 240,
            thickness: 0.15,
            showBands: false,
            footer: 0,
            padding: 0,
        })
        expect(
            layoutGaugeText({ layout: tiny, measure, fontFamily: 'x', valueText: '42%', labelText: 'CPU' }).label
        ).toBeNull()
    })

    it.each([
        ['the center', 0, 0, true],
        ['the outer edge of the ring', 1, 0, true],
        ['a corner of the box, outside the ring', 1.2, 1.2, false],
    ])('hit-tests %s for the tooltip', (_name, dx, dy, expected) => {
        const layout = computeGaugeLayout({
            width: 400,
            height: 400,
            sweep: 360,
            thickness: 0.15,
            showBands: false,
            footer: 0,
            padding: 0,
        })
        const point = { x: layout.cx + dx * layout.outerRadius, y: layout.cy + dy * layout.outerRadius }
        expect(isOverGauge(layout, point.x, point.y)).toBe(expected)
    })
})
