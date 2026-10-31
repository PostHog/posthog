import { splitHighlightTitle } from './todayFeedText'

describe('splitHighlightTitle', () => {
    test.each([
        [
            'Workflow ‘Trial ending reminder’ failed 37 times in the last 7 days',
            { title: 'Workflow ‘Trial ending reminder’ failed 37 times', quote: null, period: 'Last 7 days' },
        ],
        [
            '214 users saw the new error ‘TypeError: Cannot read properties of null’',
            { title: '214 users saw the new error', quote: 'TypeError: Cannot read properties of null', period: null },
        ],
        [
            '‘Refunds’ increased by 39% last week',
            { title: '‘Refunds’ increased by 39%', quote: null, period: 'Last week' },
        ],
        [
            'Alert ‘Checkout conversion’ is firing',
            { title: 'Alert ‘Checkout conversion’ is firing', quote: null, period: null },
        ],
    ])('splits %s', (text, expected) => {
        expect(splitHighlightTitle(text)).toEqual(expected)
    })
})
