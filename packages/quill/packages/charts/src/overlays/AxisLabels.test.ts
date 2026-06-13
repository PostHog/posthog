import { measureLabelWidth } from '../utils/text-measure'
import { computeVisibleValueTicks, computeVisibleXLabels } from './AxisLabels'

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
