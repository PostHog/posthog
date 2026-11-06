import { computeBestFitSegments } from './best-fit'
import type { BestFitSegment } from './best-fit'
import type { ScatterPointPosition } from './scatter-layout'

const positions = (seriesIndex: number, color: string, coords: [number, number][]): ScatterPointPosition[] =>
    coords.map(([x, y], i) => ({ index: i, seriesIndex, x, y, radius: 3, color, shape: 'circle' }))

describe('computeBestFitSegments', () => {
    it.each<[string, [number, number][], BestFitSegment]>([
        [
            // Off-line middle point, so a join of the outermost two would give y0: 0, y1: 3 instead.
            'least squares rather than a join of the outermost points',
            [
                [0, 0],
                [1, 0],
                [2, 3],
            ],
            { seriesIndex: 0, color: '#f00', x0: 0, y0: -0.5, x1: 2, y1: 2.5 },
        ],
        [
            'a line ending on the outermost of the points',
            [
                [10, 20],
                [20, 40],
                [30, 60],
            ],
            { seriesIndex: 0, color: '#f00', x0: 10, y0: 20, x1: 30, y1: 60 },
        ],
    ])('fits %s', (_, coords, expected) => {
        expect(computeBestFitSegments(positions(0, '#f00', coords), ['#f00'])).toEqual([expected])
    })

    it('fits each series on its own, so one cloud cannot flatten another', () => {
        const rising: [number, number][] = [
            [0, 0],
            [10, 10],
        ]
        const falling: [number, number][] = [
            [0, 10],
            [10, 0],
        ]

        const segments = computeBestFitSegments(
            [...positions(0, '#f00', rising), ...positions(1, '#00f', falling)],
            ['#f00', '#00f']
        )

        // Fitted together these cancel into one flat line through both.
        expect(segments).toEqual([
            { seriesIndex: 0, color: '#f00', x0: 0, y0: 0, x1: 10, y1: 10 },
            { seriesIndex: 1, color: '#00f', x0: 0, y0: 10, x1: 10, y1: 0 },
        ])
    })

    it('takes its color from the series, so a highlighted point cannot repaint the line', () => {
        const highlighted = positions(0, '#f00', [
            [0, 0],
            [10, 10],
        ])
        highlighted[0].color = '#0f0'

        expect(computeBestFitSegments(highlighted, ['#f00'])).toEqual([
            { seriesIndex: 0, color: '#f00', x0: 0, y0: 0, x1: 10, y1: 10 },
        ])
    })

    // Both leave the gradient undefined, which reaches the canvas as NaN coordinates.
    it.each<[string, [number, number][]]>([
        ['has a single point', [[5, 5]]],
        [
            'stacks every point at one x',
            [
                [5, 1],
                [5, 9],
            ],
        ],
    ])('draws no line for a series that %s', (_, coords) => {
        expect(computeBestFitSegments(positions(0, '#f00', coords), ['#f00'])).toEqual([])
    })
})
