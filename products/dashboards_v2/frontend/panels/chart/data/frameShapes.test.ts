import type { DataFrame } from '../../../query/queryTypes'
import { boxPlotFromFrames, categoriesFromFrames, flameFromFrames } from './frameShapes'

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

describe('frameShapes', () => {
    it.each([
        { shape: 'a row per category', frames: [rows(['a', 'b'], [3, undefined])], expected: [3, 0] },
        { shape: 'a frame per series', frames: [series('a', [1, null, 2]), series('b', [4])], expected: [3, 4] },
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
})
