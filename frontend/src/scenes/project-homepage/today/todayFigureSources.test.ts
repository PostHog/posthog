import { dayjs } from 'lib/dayjs'

import { anchorToday, figureSource, researchNotes } from './todayFigureSources'
import { signal } from './todayTestFixtures'

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
        [
            'the signal that states the figure',
            { text: '2,316', value: '2,316', noun: 'people' },
            [signal({ signal_id: 'carts', content: 'Saved carts were opened by 2316 people in 30 days.' })],
            [],
            { kind: 'signal', excerpt: 'Saved carts were opened by 2,316 people in 30 days.', parts: null },
        ],
        [
            'a small figure only when its noun matches',
            { text: '14', value: '14', noun: 'days' },
            [signal({ content: 'Retries happened 14 times today.' })],
            [],
            null,
        ],
        [
            'the newest research that states the figure',
            { text: '18', value: '18', noun: 'people' },
            [],
            [
                {
                    type: 'priority_judgment',
                    created_at: '2026-10-02T00:00:00Z',
                    content: { explanation: 'The empty cart page was shown to 18 people.' },
                },
                {
                    type: 'priority_judgment',
                    created_at: '2026-09-01T00:00:00Z',
                    content: { explanation: 'The empty cart page was shown to 18 people last month.' },
                },
            ],
            { kind: 'research', excerpt: 'The empty cart page was shown to 18 people.', parts: null },
        ],
        [
            'a total the research gives as parts',
            { text: '212', value: '212', noun: 'failed' },
            [],
            [
                {
                    type: 'priority_judgment',
                    created_at: '2026-10-02T00:00:00Z',
                    content: { explanation: 'Failed checkout requests rose to 150 timeout and 62 declined.' },
                },
            ],
            {
                kind: 'research',
                excerpt: 'Failed checkout requests rose to 150 timeout and 62 declined.',
                parts: ['150', '62'],
            },
        ],
    ])('traces %s', (_, figure, signals, artefacts, expected) => {
        const source = figureSource(
            figure,
            { signals, research: researchNotes(artefacts), summary: null },
            'We logged 212 failed checkout requests, shown to 18 people.'
        )
        expect(source ? { kind: source.kind, excerpt: source.excerpt, parts: source.parts } : null).toEqual(expected)
    })
})
