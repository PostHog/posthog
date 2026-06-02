import { computeVisibleYLabels } from './AxisLabels'

describe('computeVisibleYLabels', () => {
    const labels = ['a', 'b', 'c', 'd', 'e']

    it('keeps every label when rows have room', () => {
        // 40px apart — far more than the ~16px a 12px label needs.
        const yScale = (label: string): number => labels.indexOf(label) * 40
        const visible = computeVisibleYLabels(labels, yScale)
        expect(visible.map((v) => v.text)).toEqual(labels)
    })

    it('thins out labels when bands are compressed', () => {
        // 6px apart — labels would overlap, so only a spaced-out subset survives.
        const yScale = (label: string): number => labels.indexOf(label) * 6
        const visible = computeVisibleYLabels(labels, yScale)
        expect(visible.length).toBeLessThan(labels.length)
        // The first label is always anchored, and kept labels never overlap.
        expect(visible[0].text).toBe('a')
        for (let i = 1; i < visible.length; i++) {
            expect(visible[i].y - visible[i - 1].y).toBeGreaterThanOrEqual(12)
        }
    })

    it('drops labels the formatter nulls out (band-shared breakdown rows)', () => {
        const yScale = (label: string): number => labels.indexOf(label) * 40
        const formatter = (value: string): string | null => (value === 'c' ? null : value)
        const visible = computeVisibleYLabels(labels, yScale, formatter)
        expect(visible.map((v) => v.text)).toEqual(['a', 'b', 'd', 'e'])
    })

    it('skips labels with no finite coordinate', () => {
        const yScale = (label: string): number | undefined => (label === 'b' ? undefined : labels.indexOf(label) * 40)
        const visible = computeVisibleYLabels(labels, yScale)
        expect(visible.map((v) => v.text)).toEqual(['a', 'c', 'd', 'e'])
    })

    it('orders by coordinate before thinning so out-of-order labels still pack correctly', () => {
        const coords: Record<string, number> = { a: 100, b: 0, c: 50, d: 25, e: 75 }
        const yScale = (label: string): number => coords[label]
        const visible = computeVisibleYLabels(labels, yScale)
        const ys = visible.map((v) => v.y)
        expect(ys).toEqual([...ys].sort((x, y) => x - y))
    })
})
