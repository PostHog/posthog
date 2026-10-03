import { figuresToMark, findFigures, highlightSegments } from './todayFigures'

describe('todayFigures', () => {
    test.each([
        [
            'counts with units',
            'Crashing across 41 teams, 2,316 people and 120–150 users a week.',
            ['41', '2,316', '120–150'],
        ],
        ['not times, dates, versions or years', 'At 07:00 on 2026-08-12 an SDK-5.6 build failed in 2026.', []],
        ['not the time window of a claim', 'In the trailing 14 days 63 people waited 9 minutes.', ['63', '9 minutes']],
        ['not a day of the month', 'Over the 30 days to 1 Sep, 4,512 orders failed.', ['4,512']],
        ['amounts of money', 'About $4.2K in spend and €40 a seat, filed as #123 on $pageview.', ['$4.2K', '€40']],
    ])('finds figures in %s', (_, text, expected) => {
        expect(findFigures(text).map((figure) => figure.text)).toEqual(expected)
    })

    test.each([
        [
            'each backing number once and never a day of the month',
            '4 failures on 2 Aug, 12 on 12 Aug, and 31 on 14 Aug.',
            ['4', '12', '31'],
            ['4', '12', '31'],
        ],
        ['an amount of money with its currency sign', 'About $4.2K in seven-day spend.', ['4.2'], ['$4.2K']],
    ])('emphasizes %s', (_, text, values, expected) => {
        const segments = highlightSegments(text, values)
        expect(segments.filter((segment) => segment.marked).map((segment) => segment.text)).toEqual(expected)
        expect(segments.map((segment) => segment.text).join('')).toEqual(text)
    })

    test('marks counts of people before other figures', () => {
        const figures = findFigures(
            'We logged 212 failed requests across 57 people and showed it 33 times to 18 people.'
        )
        expect([...figuresToMark(figures, 3)].map((figure) => figure.text)).toEqual(['57', '18', '212'])
    })
})
