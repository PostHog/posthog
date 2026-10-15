import {
    PreferredTodaySectionHeights,
    TodaySectionHeights,
    TodaySectionInput,
    layoutTodaySections,
    resizeTodaySections,
} from './todaySectionLayout'

const section = (id: TodaySectionInput['id'], contentHeight: number, open = true): TodaySectionInput => ({
    id,
    open,
    contentHeight,
})

describe('todaySectionLayout', () => {
    test.each<[string, TodaySectionInput[], number, PreferredTodaySectionHeights, TodaySectionHeights]>([
        [
            'recent absorbs the height a short pinned section leaves',
            [section('pinned', 100), section('recent', 50)],
            600,
            {},
            { pinned: 100, recent: 500 },
        ],
        [
            'a long pinned section stops at the share cap',
            [section('pinned', 1000), section('recent', 1000)],
            500,
            {},
            { pinned: 200, recent: 300 },
        ],
        [
            'a dragged height wins over the share cap',
            [section('pinned', 1000), section('recent', 1000)],
            500,
            { pinned: 120 },
            { pinned: 120, recent: 380 },
        ],
        [
            'a collapsed recent gets no height and pinned fills in its place',
            [section('pinned', 1000), section('recent', 1000, false)],
            600,
            {},
            { pinned: 600, recent: 0 },
        ],
        [
            'pinned does not grow past its content when recent is collapsed',
            [section('pinned', 50), section('recent', 1000, false)],
            600,
            {},
            { pinned: 50, recent: 0 },
        ],
        [
            'pinned shrinks so recent keeps its minimum height',
            [section('pinned', 500), section('recent', 500)],
            100,
            { pinned: 90 },
            { pinned: 44, recent: 56 },
        ],
    ])('%s', (_, sections, available, preferred, expected) => {
        expect(layoutTodaySections(sections, available, preferred)).toEqual(expected)
    })

    test('a drag clamps the upper section at its minimum and never stores the filling section', () => {
        expect(
            resizeTodaySections({
                sections: [section('pinned', 1000), section('recent', 1000)],
                heights: { pinned: 200, recent: 300 },
                upper: 'pinned',
                lower: 'recent',
                delta: -500,
                preferred: {},
            })
        ).toEqual({ pinned: 40 })
    })
})
