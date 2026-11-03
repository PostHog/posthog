import {
    computeGaugeLayout,
    gaugeFraction,
    layoutGaugeText,
    resolveGaugeBounds,
    ringSectorBox,
    targetTickSize,
    thresholdBands,
} from './gauge-layout'
import type { GaugeThreshold, ResolveGaugeBoundsInput } from './gauge-layout'

const steps = (...values: number[]): GaugeThreshold[] => values.map((value, i) => ({ value, color: `c${i}` }))

describe('gauge layout', () => {
    it.each<[string, ResolveGaugeBoundsInput, { min: number; max: number }]>([
        [
            'explicit min and max win over value and thresholds',
            { value: 500, min: 0, max: 100, thresholds: steps(50, 900) },
            { min: 0, max: 100 },
        ],
        ['thresholds span the range in any order', { value: 60, thresholds: steps(90, 0, 50) }, { min: 0, max: 90 }],
        [
            'a value under the lowest threshold widens the range to 0',
            { value: 30, thresholds: steps(70, 90) },
            { min: 0, max: 90 },
        ],
        [
            'the range grows to contain a value past the last threshold',
            { value: 150, thresholds: steps(50, 90) },
            { min: 50, max: 150 },
        ],
        ['a value alone gets 0 to 1', { value: 0.4 }, { min: 0, max: 1 }],
    ])('resolves bounds: %s', (_name, input, expected) => {
        expect(resolveGaugeBounds(input)).toEqual(expected)
    })

    it('clamps the fraction to the range, and reads full at the value when min equals max', () => {
        expect(gaugeFraction(140, { min: 0, max: 100 })).toBe(1)
        expect(gaugeFraction(5, { min: 5, max: 5 })).toBe(1)
        expect(gaugeFraction(4, { min: 5, max: 5 })).toBe(0)
    })

    it('clips threshold bands to the range and drops the ones outside it', () => {
        const bands = thresholdBands(steps(0, 70, 90, 200), { min: 0, max: 100 })
        expect(bands.map(({ from, to }) => ({ from, to }))).toEqual([
            { from: 0, to: 70 },
            { from: 70, to: 90 },
            { from: 90, to: 100 },
        ])
    })

    it.each([
        [400, 120, 240, false],
        [300, 300, 360, false],
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
})
