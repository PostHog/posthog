import type { DataFrame } from '../../../query/queryTypes'
import {
    MAX_CATEGORIES,
    boxPlotFromFrames,
    categoriesFromFrames,
    flameFromFrames,
    flowsFromFrames,
    slopeFromFrames,
} from './frameShapes'

const rows = (labels: string[], values: unknown[]): DataFrame => ({
    fields: [
        { name: 'label', type: 'string', values: labels },
        { name: 'value', type: 'number', values },
    ],
})
const series = (name: string, values: (number | null)[]): DataFrame => ({
    name,
    fields: [
        { name: 'time', type: 'time', values: values.map((_, day) => `2026-11-0${day + 1}`) },
        { name: 'value', type: 'number', values },
    ],
})

const total: DataFrame = { name: 't', fields: [{ name: 'v', type: 'number', values: [7] }] }

describe('frameShapes', () => {
    it.each([
        { shape: 'a row per category', frames: [rows(['a', 'b'], [3, undefined])], expected: [3, 0] },
        { shape: 'a frame per series', frames: [series('a', [1, null, 2]), series('b', [4])], expected: [3, 4] },
        {
            shape: 'a total without times',
            frames: [total],
            expected: [7],
        },
        { shape: 'rows from every target', frames: [rows(['a'], [1]), rows(['a'], [2])], expected: [1, 2] },
    ])('values each category from $shape without a NaN', ({ frames, expected }) => {
        expect(categoriesFromFrames(frames).map((one) => one.data[0])).toEqual(expected)
    })

    it('summarizes each frame into interpolated quartiles, and an empty frame into no box', () => {
        const { series: boxes } = boxPlotFromFrames([series('a', [10, 1, 3, 2]), series('b', [])])

        expect(boxes[0].data).toEqual([{ min: 1, p25: 1.75, median: 2.5, mean: 4, p75: 4.75, max: 10 }, null])
    })

    it('merges folded stacks that share a prefix and sums their widths up the tree', () => {
        const root = flameFromFrames([rows(['main;render', 'main;fetch', 'idle'], [3, 2, 1])])

        expect(root.value).toBe(6)
        expect(root.children?.map((child) => [child.name, child.value])).toEqual([
            ['main', 5],
            ['idle', 1],
        ])
        expect(root.children?.[0].children?.map((child) => child.name)).toEqual(['render', 'fetch'])
    })

    it('keeps a gap at a slope end the series has no value for', () => {
        const { series: slopes } = slopeFromFrames([series('a', [null, 10, 20])])

        expect(slopes[0].data).toEqual([NaN, 20])
    })

    it('keeps the root of a fallback flow apart from a category named like it', () => {
        const { links } = flowsFromFrames([series('All', [1, 2])])

        expect(links).toHaveLength(1)
        expect(links[0].source).not.toBe(links[0].target)
    })

    it('keeps only the largest categories, in their order', () => {
        const count = MAX_CATEGORIES + 10
        const labels = Array.from({ length: count }, (_, row) => `c${row}`)
        const values = labels.map((_, row) => (row === 0 ? 1_000 : row))

        const kept = categoriesFromFrames([rows(labels, values)]).map((one) => one.label)

        expect(kept).toHaveLength(MAX_CATEGORIES)
        expect(kept[0]).toBe('c0')
        expect(kept).not.toContain('c1')
    })

    it('bounds the tree a single long stack builds', () => {
        const root = flameFromFrames([rows(['a;'.repeat(100_000)], [1])])

        const ids: string[] = []
        for (let node = root.children?.[0]; node; node = node.children?.[0]) {
            ids.push(node.id ?? '')
        }
        expect(ids.length).toBeLessThanOrEqual(256)
        expect(Math.max(...ids.map((id) => id.length))).toBeLessThan(20)
    })
})
