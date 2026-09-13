import { eventSpanAttributes } from './span-attributes'

describe('eventSpanAttributes', () => {
    it.each([
        ['non-object input', 'nope', {}],
        ['unknown shape', { foo: 'bar' }, {}],
        [
            'team + raw event',
            { team: { id: 7 }, event: { event: '$pageview', distinct_id: 'u1' } },
            { team_id: 7, distinct_id: 'u1', event: '$pageview' },
        ],
        [
            'teamId + normalizedEvent wins over event',
            {
                teamId: 3,
                event: { event: 'raw', distinct_id: 'r' },
                normalizedEvent: { event: 'norm', distinct_id: 'n' },
            },
            { team_id: 3, distinct_id: 'n', event: 'norm' },
        ],
        [
            'preparedEvent uses camelCase distinctId',
            { team: { id: 9 }, preparedEvent: { event: 'e', distinctId: 'p' } },
            { team_id: 9, distinct_id: 'p', event: 'e' },
        ],
        ['team id from the event when no team object', { event: { team_id: 5 } }, { team_id: 5 }],
        ['ignores fields of the wrong type', { teamId: '5', event: { event: 1, distinct_id: null } }, {}],
    ])('%s', (_name, input, expected) => {
        expect(eventSpanAttributes(input)).toEqual(expected)
    })
})
