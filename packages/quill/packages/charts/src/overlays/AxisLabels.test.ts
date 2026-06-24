import { scaleLog } from 'd3-scale'

import { measureLabelWidth } from '../utils/text-measure'
import { computeVisibleValueTicks, computeVisibleXLabels, computeVisibleYTicks } from './AxisLabels'

describe('computeVisibleXLabels', () => {
    const longUrl = 'https://app.posthog.com/project/1/insights/abc123/edit?with=a&very=long&query=string'
    // Spread labels far apart so the overlap filter keeps every candidate — we only assert truncation here.
    const wideScale =
        (labels: string[]) =>
        (label: string): number =>
            labels.indexOf(label) * 10000

    it('leaves title undefined for every label when no max width is set', () => {
        const labels = ['short', longUrl]
        const visible = computeVisibleXLabels(labels, wideScale(labels), undefined, 0)

        expect(visible).toHaveLength(2)
        expect(visible.every((v) => v.title === undefined)).toBe(true)
        expect(visible.every((v) => v.text === labels[v.index])).toBe(true)
    })

    it('sets title to the full value only on labels that were truncated', () => {
        const labels = ['short', longUrl]
        // Budget fits "short" but not the URL, so only the URL truncates.
        const budget = measureLabelWidth(longUrl) / 2
        const visible = computeVisibleXLabels(labels, wideScale(labels), undefined, budget)

        const short = visible.find((v) => v.index === 0)
        const long = visible.find((v) => v.index === 1)
        expect(short?.title).toBeUndefined()
        expect(short?.text).toBe('short')
        expect(long?.title).toBe(longUrl)
        expect(long?.text.endsWith('…')).toBe(true)
    })

    it('drops labels whose scale returns null', () => {
        const labels = ['a', 'b']
        const visible = computeVisibleXLabels(labels, (label) => (label === 'a' ? 0 : undefined))

        expect(visible.map((v) => v.index)).toEqual([0])
    })
})

describe('computeVisibleValueTicks', () => {
    const fmt = (v: number): string => v.toLocaleString('en-US')

    it('drops value ticks whose wide labels would overlap, always keeping the first', () => {
        // 10 ticks packed into ~120px (every ~13px) — far too tight for "450,000"-style labels.
        const ticks = Array.from({ length: 10 }, (_, i) => i * 50_000)
        const valueToCoord = (v: number): number => (v / 450_000) * 120

        const visible = computeVisibleValueTicks(ticks, valueToCoord, fmt)

        expect(visible.length).toBeLessThan(ticks.length)
        expect(visible[0].tick).toBe(0)
        // Survivors stay strictly left-to-right with no measured-label overlap.
        for (let i = 1; i < visible.length; i++) {
            const prevRight = visible[i - 1].x + measureLabelWidth(visible[i - 1].text) / 2
            const currLeft = visible[i].x - measureLabelWidth(visible[i].text) / 2
            expect(currLeft).toBeGreaterThanOrEqual(prevRight)
        }
    })

    it('keeps numeric ticks separated by a small but legible gap', () => {
        // Two wide labels whose boxes sit ~14px apart: comfortably readable, but under the 20px gap
        // the category-label path enforces — value ticks must not inherit that aggressive culling.
        const ticks = [100_000, 120_000]
        const [w0, w1] = ticks.map((t) => measureLabelWidth(fmt(t)))
        const x0 = w0 / 2 + 10
        const x1 = x0 + w0 / 2 + 14 + w1 / 2
        const valueToCoord = (v: number): number => (v === ticks[0] ? x0 : x1)

        const visible = computeVisibleValueTicks(ticks, valueToCoord, fmt)

        expect(visible.map((v) => v.tick)).toEqual(ticks)
    })

    it.each([
        {
            description: 'keeps every tick when they are spread far apart',
            ticks: [0, 100, 200],
            valueToCoord: (v: number): number => v * 10,
            expected: [0, 100, 200],
        },
        {
            description: 'skips ticks whose coordinate is not finite',
            ticks: [0, 50, 100],
            valueToCoord: (v: number): number => (v === 50 ? NaN : v * 10),
            expected: [0, 100],
        },
    ])('$description', ({ ticks, valueToCoord, expected }) => {
        const visible = computeVisibleValueTicks(ticks, valueToCoord, fmt)

        expect(visible.map((v) => v.tick)).toEqual(expected)
    })
})

describe('computeVisibleYTicks', () => {
    it('keeps every linear tick when comfortably spaced', () => {
        const ticks = [0, 25, 50, 75, 100]
        // 50px apart — far beyond the ~16px overlap threshold.
        const valueToCoord = (v: number): number => 250 - (v / 100) * 200

        expect(computeVisibleYTicks(ticks, valueToCoord)).toEqual(ticks)
    })

    it('thins an overcrowded log axis down to non-overlapping labels, preferring round values', () => {
        // d3 log ticks for a 1→1000 domain: 1..9, 10..90, 100..900, 1000 — far too many to label
        // in a 300px gutter without overlap.
        const scale = scaleLog().domain([1, 1000]).range([300, 0])
        const ticks = scale.ticks() as number[]

        const visible = computeVisibleYTicks(ticks, (v) => scale(v))

        // No two surviving labels sit closer than the overlap threshold.
        const coords = visible.map((t) => scale(t)).sort((a, b) => a - b)
        for (let i = 1; i < coords.length; i++) {
            expect(coords[i] - coords[i - 1]).toBeGreaterThanOrEqual(16)
        }
        // The powers of ten — the roundest values — all survive.
        expect(visible).toEqual(expect.arrayContaining([1, 10, 100, 1000]))
        // Ascending order is preserved.
        expect([...visible].sort((a, b) => a - b)).toEqual(visible)
    })

    it('prefers a power of ten over an adjacent sub-decade tick when only one fits', () => {
        // 90 and 100 map ~5px apart — too close to both label; the rounder 100 must win.
        const valueToCoord = (v: number): number => (v === 90 ? 105 : v === 100 ? 100 : 300 - v)
        const visible = computeVisibleYTicks([90, 100], valueToCoord)

        expect(visible).toEqual([100])
    })

    it('drops ticks whose coordinate is not finite', () => {
        const valueToCoord = (v: number): number => (v === 50 ? NaN : 200 - v)

        expect(computeVisibleYTicks([0, 50, 100], valueToCoord)).toEqual([0, 100])
    })
})
