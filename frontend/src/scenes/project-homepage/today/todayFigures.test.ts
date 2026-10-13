import { highlightSegments, quoteSegments } from './todayFigures'

describe('todayFigures', () => {
    test.each([
        [
            'each backing number once and never a day of the month',
            '4 failures on 2 Aug, 12 on 12 Aug, and 31 on 14 Aug.',
            ['4', '12', '31'],
            ['4', '12', '31'],
        ],
        ['an amount of money with its currency sign', 'About $4.2K in seven-day spend.', ['4.2'], ['$4.2K']],
        [
            'numbers in the order the text states them',
            '30,000 calls at 120 ms each.',
            ['120', '30,000'],
            ['30,000', '120 ms'],
        ],
    ])('emphasizes %s', (_, text, values, expected) => {
        const segments = highlightSegments(text, values)
        expect(segments.filter((segment) => segment.marked).map((segment) => segment.text)).toEqual(expected)
        expect(segments.map((segment) => segment.text).join('')).toEqual(text)
    })

    test('emphasizes the exact number a source states when its value repeats', () => {
        const quote = { excerpt: '4 events came from 4 issues.', highlight: { start: 19, end: 20 } }
        expect(quoteSegments(quote, '4')).toEqual([
            { text: '4 events came from ', marked: false },
            { text: '4', marked: true },
            { text: ' issues.', marked: false },
        ])
    })
})
