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
            'recent absorbs the height the short sections leave',
            [section('pinned', 100), section('recent', 50), section('spaces', 80)],
            600,
            {},
            { pinned: 100, recent: 420, spaces: 80 },
        ],
        [
            'long sections stop at the share cap',
            [section('recent', 1000), section('spaces', 1000)],
            500,
            {},
            { pinned: 0, recent: 300, spaces: 200 },
        ],
        [
            'a dragged height wins over the share cap',
            [section('recent', 1000), section('spaces', 1000)],
            500,
            { spaces: 120 },
            { pinned: 0, recent: 380, spaces: 120 },
        ],
        [
            'a collapsed section gets no height and spaces fill in its place',
            [section('pinned', 100), section('recent', 1000, false), section('spaces', 1000)],
            600,
            {},
            { pinned: 100, recent: 0, spaces: 500 },
        ],
        [
            'short sections do not grow past their content when recent is collapsed',
            [section('pinned', 50), section('recent', 1000, false), section('spaces', 80)],
            600,
            {},
            { pinned: 50, recent: 0, spaces: 80 },
        ],
        [
            'other sections shrink so recent keeps its minimum height',
            [section('pinned', 500), section('recent', 500)],
            100,
            { pinned: 90 },
            { pinned: 44, recent: 56, spaces: 0 },
        ],
    ])('%s', (_, sections, available, preferred, expected) => {
        expect(layoutTodaySections(sections, available, preferred)).toEqual(expected)
    })

    test('a drag clamps the lower section at its minimum and never stores the filling section', () => {
        expect(
            resizeTodaySections({
                sections: [section('recent', 1000), section('spaces', 1000)],
                heights: { pinned: 0, recent: 300, spaces: 200 },
                upper: 'recent',
                lower: 'spaces',
                delta: 500,
                preferred: {},
            })
        ).toEqual({ spaces: 40 })
    })
})
