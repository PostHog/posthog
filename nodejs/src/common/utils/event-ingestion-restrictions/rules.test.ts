import { EventContext, RestrictionFilters } from './rules'

describe('RestrictionFilters', () => {
    describe('matches() - AND between filter types, OR within each type', () => {
        const testCases = [
            {
                name: 'single distinct_id filter',
                filters: { distinctIds: ['u1'] },
                expectations: [
                    { event: { distinct_id: 'u1' }, expected: true },
                    { event: { distinct_id: 'u2' }, expected: false },
                    { event: { session_id: 'u1' }, expected: false }, // right value, wrong key
                    { event: { event: 'u1' }, expected: false }, // right value, wrong key
                    { event: {}, expected: false },
                ],
            },
            {
                name: 'OR within: multiple values in distinct_id filter',
                filters: { distinctIds: ['u1', 'u2', 'u3'] },
                expectations: [
                    { event: { distinct_id: 'u1' }, expected: true },
                    { event: { distinct_id: 'u2' }, expected: true },
                    { event: { distinct_id: 'u3' }, expected: true },
                    { event: { distinct_id: 'u4' }, expected: false },
                    { event: { session_id: 'u1' }, expected: false }, // right value, wrong key
                ],
            },
            {
                name: 'single session_id filter',
                filters: { sessionIds: ['s1'] },
                expectations: [
                    { event: { session_id: 's1' }, expected: true },
                    { event: { session_id: 's2' }, expected: false },
                    { event: { distinct_id: 's1' }, expected: false }, // right value, wrong key
                    { event: { event: 's1' }, expected: false }, // right value, wrong key
                    { event: {}, expected: false },
                ],
            },
            {
                name: 'single event_name filter',
                filters: { eventNames: ['$pageview'] },
                expectations: [
                    { event: { event: '$pageview' }, expected: true },
                    { event: { event: '$identify' }, expected: false },
                    { event: { distinct_id: '$pageview' }, expected: false }, // right value, wrong key
                    { event: { uuid: '$pageview' }, expected: false }, // right value, wrong key
                    { event: {}, expected: false },
                ],
            },
            {
                name: 'single uuid filter',
                filters: { eventUuids: ['uuid-123'] },
                expectations: [
                    { event: { uuid: 'uuid-123' }, expected: true },
                    { event: { uuid: 'uuid-456' }, expected: false },
                    { event: { distinct_id: 'uuid-123' }, expected: false }, // right value, wrong key
                    { event: { session_id: 'uuid-123' }, expected: false }, // right value, wrong key
                    { event: {}, expected: false },
                ],
            },
            {
                name: 'empty filters match everything',
                filters: {},
                expectations: [
                    { event: {}, expected: true },
                    { event: { distinct_id: 'u1' }, expected: true },
                    {
                        event: { distinct_id: 'u1', session_id: 's1', event: '$pageview', uuid: 'uuid-123' },
                        expected: true,
                    },
                ],
            },
            {
                name: 'AND: distinct_id AND event_name',
                filters: { distinctIds: ['u1'], eventNames: ['$pageview'] },
                expectations: [
                    { event: { distinct_id: 'u1', event: '$pageview' }, expected: true },
                    { event: { distinct_id: 'u1', event: '$identify' }, expected: false },
                    { event: { distinct_id: 'u2', event: '$pageview' }, expected: false },
                    { event: { distinct_id: 'u1' }, expected: false },
                    { event: { event: '$pageview' }, expected: false },
                    { event: { session_id: 'u1', uuid: '$pageview' }, expected: false }, // right values, wrong keys
                    { event: { distinct_id: '$pageview', event: 'u1' }, expected: false }, // swapped values
                    { event: {}, expected: false },
                ],
            },
            {
                name: 'AND: all four filter types',
                filters: {
                    distinctIds: ['u1'],
                    sessionIds: ['s1'],
                    eventNames: ['$pageview'],
                    eventUuids: ['uuid-123'],
                },
                expectations: [
                    {
                        event: { distinct_id: 'u1', session_id: 's1', event: '$pageview', uuid: 'uuid-123' },
                        expected: true,
                    },
                    {
                        event: { distinct_id: 'u1', session_id: 's1', event: '$pageview', uuid: 'wrong' },
                        expected: false,
                    },
                    {
                        event: { distinct_id: 'u1', session_id: 's1', event: 'wrong', uuid: 'uuid-123' },
                        expected: false,
                    },
                    {
                        event: { distinct_id: 'u1', session_id: 'wrong', event: '$pageview', uuid: 'uuid-123' },
                        expected: false,
                    },
                    {
                        event: { distinct_id: 'wrong', session_id: 's1', event: '$pageview', uuid: 'uuid-123' },
                        expected: false,
                    },
                    { event: { distinct_id: 'u1', session_id: 's1', event: '$pageview' }, expected: false },
                    { event: { distinct_id: 'u1', session_id: 's1' }, expected: false },
                    { event: { distinct_id: 'u1' }, expected: false },
                    { event: {}, expected: false },
                ],
            },
            {
                name: 'AND with OR: multiple values per filter type',
                filters: {
                    distinctIds: ['u1', 'u2'],
                    eventNames: ['$pageview', '$screen'],
                },
                expectations: [
                    { event: { distinct_id: 'u1', event: '$pageview' }, expected: true },
                    { event: { distinct_id: 'u1', event: '$screen' }, expected: true },
                    { event: { distinct_id: 'u2', event: '$pageview' }, expected: true },
                    { event: { distinct_id: 'u2', event: '$screen' }, expected: true },
                    { event: { distinct_id: 'u3', event: '$pageview' }, expected: false },
                    { event: { distinct_id: 'u1', event: '$identify' }, expected: false },
                ],
            },
            {
                name: 'partial filter: only session_id and event_name (ignores missing filters)',
                filters: { sessionIds: ['s1'], eventNames: ['$pageview'] },
                expectations: [
                    { event: { session_id: 's1', event: '$pageview' }, expected: true },
                    { event: { distinct_id: 'any', session_id: 's1', event: '$pageview' }, expected: true },
                    { event: { session_id: 's1', event: '$pageview', uuid: 'any' }, expected: true },
                    { event: { session_id: 's1' }, expected: false },
                    { event: { event: '$pageview' }, expected: false },
                ],
            },
        ] satisfies Array<{
            name: string
            filters: { distinctIds?: string[]; sessionIds?: string[]; eventNames?: string[]; eventUuids?: string[] }
            expectations: Array<{ event: EventContext; expected: boolean }>
        }>

        for (const { name, filters, expectations } of testCases) {
            describe(name, () => {
                const restrictionFilters = new RestrictionFilters(filters)

                for (const { event, expected } of expectations) {
                    it(`event=${JSON.stringify(event)} => ${expected}`, () => {
                        expect(restrictionFilters.matches(event)).toBe(expected)
                    })
                }
            })
        }
    })
})
