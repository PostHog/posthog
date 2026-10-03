import { dayjs } from 'lib/dayjs'

import type { FigureMarkApi } from 'products/today/frontend/generated/api.schemas'

import { anchorToday, markedFigures } from './todayFigureSources'
import { signal } from './todayTestFixtures'

const LEAD = 'Since `syncCart` shipped, [checkout](https://example.com) fails for 212 users.'
const SHOWN = 'Since syncCart shipped, checkout fails for 212 users.'

function mark(figure: string, at: number, signalId: string = 'carts'): FigureMarkApi {
    return {
        text: 'lead',
        start: at,
        end: at + figure.length,
        figure,
        quote: {
            kind: 'signal',
            signal_id: signalId,
            at: '2026-10-01T10:00:00Z',
            sentence: 'Checkout failed for 212 users.',
            start: 20,
            end: 23,
        },
    }
}

describe('todayFigureSources', () => {
    test.each([
        [
            'an older quote',
            '2026-09-04T10:00:00Z',
            'A session from today hit it.',
            'A session from today [4 Sep] hit it.',
        ],
        ['a quote from today', '2026-10-03T08:00:00Z', 'A session from today hit it.', 'A session from today hit it.'],
    ])('dates "today" in %s', (_, date, text, expected) => {
        expect(anchorToday(text, date, dayjs('2026-10-03T12:00:00Z'))).toEqual(expected)
    })

    test.each([
        ['a number after code and a link', mark('212', SHOWN.indexOf('212')), [[4, 11, '212']]],
        ['no number where the page text differs', mark('212', SHOWN.indexOf('212') + 1), []],
        ['no number whose signal the page does not list', mark('212', SHOWN.indexOf('212'), 'gone'), []],
    ])('places %s', (_, figureMark, expected) => {
        const placed = markedFigures(LEAD, [figureMark], [signal({ signal_id: 'carts' })])
        expect(placed.map((figure) => [figure.segment, figure.start, figure.text])).toEqual(expected)
    })
})
