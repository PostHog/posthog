import { measureLabelWidth } from '../utils/text-measure'
import { computeVisibleXLabels } from './AxisLabels'

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
