import { flattenScatterPoints } from './scatter-data'
import { xLabelEdgeReserve } from './scatter-scales'
import type { ScatterSeries } from './types'

jest.mock('../../utils/text-measure', () => ({
    ...jest.requireActual('../../utils/text-measure'),
    measureLabelWidth: (text: string) => text.length * 10,
}))

const POINTS = flattenScatterPoints([
    {
        key: 'a',
        label: 'A',
        points: [
            { x: 30, y: 1 },
            { x: 10, y: 2 },
        ],
    },
] satisfies ScatterSeries[])

describe('xLabelEdgeReserve', () => {
    // measureLabelWidth is mocked above at 10px per character, over the 4px shared edge padding.
    it.each<[string, Parameters<typeof xLabelEdgeReserve>, number]>([
        // Ticks run to '$30' over the points' 10–30 span: 3 characters, so 15px of overhang.
        ['half the widest tick label, formatted the way the axis formats it', [POINTS, undefined, (v) => `$${v}`], 19],
        ['a pinned domain rather than the points', [POINTS, [0, 1000], (v) => `$${v}`], 29],
        ['nothing when there is no point to label', [[], undefined, undefined], 0],
    ])('reserves %s', (_, args, expected) => {
        expect(xLabelEdgeReserve(...args)).toBe(expected)
    })
})
