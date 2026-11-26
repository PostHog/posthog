import { aiRerunRefresh } from './aiRerunRefresh'

describe('aiRerunRefresh', () => {
    const earlier = '2026-11-26T10:00:00+00:00'
    const later = '2026-11-26T10:05:00+00:00'

    test.each([
        ['no triage yet', null, { triage: null, finished: false }],
        [
            'the earlier run, still shown as done',
            { status: 'done', finished_at: earlier },
            { triage: null, finished: false },
        ],
        [
            'the new run in progress',
            { status: 'in_progress', finished_at: earlier },
            { triage: { status: 'in_progress', finished_at: earlier }, finished: false },
        ],
        [
            'the new run finished',
            { status: 'done', finished_at: later },
            { triage: { status: 'done', finished_at: later }, finished: true },
        ],
    ])('%s', (_name, fetched, expected) => {
        expect(aiRerunRefresh(fetched, earlier)).toEqual(expected)
    })
})
