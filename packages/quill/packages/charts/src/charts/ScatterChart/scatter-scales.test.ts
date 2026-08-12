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

describe('scatter-scales', () => {
    describe('xLabelEdgeReserve', () => {
        // measureLabelWidth is mocked above at 10px per character.
        it('reserves half the widest tick label, formatted the way the axis formats it', () => {
            // Ticks run to '$30' over the points' 10–30 span: 3 characters, so 15px of overhang.
            expect(xLabelEdgeReserve(POINTS, undefined, (v) => `$${v}`)).toBe(15 + 4)
        })

        it('follows a pinned domain rather than the points', () => {
            expect(xLabelEdgeReserve(POINTS, [0, 1000], (v) => `$${v}`)).toBe(25 + 4)
        })

        it('reserves nothing when there is no point to label', () => {
            expect(xLabelEdgeReserve([], undefined, undefined)).toBe(0)
        })
    })
})
