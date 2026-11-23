import { GutterThread, stackGutterThreads } from './gutterThreadLayout'

describe('stackGutterThreads', () => {
    const GAP = 10
    const threads = (...entries: [anchorTop: number, height: number][]): GutterThread[] =>
        entries.map(([anchorTop, height]) => ({ anchorTop, height }))

    it.each([
        {
            name: 'lines each thread up with its own anchor when they do not overlap',
            input: threads([100, 50], [300, 50], [500, 50]),
            activeIndex: -1,
            minTop: 0,
            expected: [100, 300, 500],
        },
        {
            name: 'pushes a thread down past the one above it when they would overlap',
            input: threads([100, 80], [120, 80], [400, 50]),
            activeIndex: -1,
            minTop: 0,
            expected: [100, 190, 400],
        },
        {
            name: 'keeps the active thread at its anchor and moves the threads above it up',
            input: threads([100, 80], [120, 80], [140, 80]),
            activeIndex: 2,
            minTop: -100,
            expected: [-40, 50, 140],
        },
        {
            name: 'packs the threads above the active one from the top when they do not fit',
            input: threads([100, 80], [120, 80], [140, 80]),
            activeIndex: 2,
            minTop: 50,
            expected: [50, 140, 230],
        },
        {
            name: 'ignores an active index that is out of range',
            input: threads([100, 80], [120, 80]),
            activeIndex: 5,
            minTop: 0,
            expected: [100, 190],
        },
    ])('$name', ({ input, activeIndex, minTop, expected }) => {
        expect(stackGutterThreads(input, activeIndex, minTop, GAP)).toEqual(expected)
    })
})
