import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { CyclotronJobFilterPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import {
    flagCallsOutsideEventsFilters,
    matchesOnlyFlagCallsOutsideEvents,
    withFlagCallCounts,
} from './flagCallsMatching'
import { MatchingFiltersInput, matchingFiltersToPropertyGroup } from './matchingFilters'

const FLAG_CALLED = { id: '$feature_flag_called', name: '$feature_flag_called', type: 'events' as const, order: 0 }
const PAGEVIEW = { id: '$pageview', name: '$pageview', type: 'events' as const, order: 1 }
const ALL_EVENTS = { id: '', name: 'All events', type: 'events' as const, order: 2 }
const ACTION = { id: '12', name: 'Signed up', type: 'actions' as const, order: 3 }
const GLOBAL_PROPERTY = {
    key: '$browser',
    value: 'Chrome',
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
} as CyclotronJobFilterPropertyFilter
const FLAG_EVALUATIONS_ONLY_TEAM = { ...MOCK_DEFAULT_TEAM, flag_evaluations_mode: FlagEvaluationsModeEnumApi.Number2 }

describe('flagCallsMatching', () => {
    it.each<[string, MatchingFiltersInput, MatchingFiltersInput | null]>([
        [
            'keeps only the flag call matcher and the global filters',
            { events: [PAGEVIEW, FLAG_CALLED], actions: [ACTION], properties: [GLOBAL_PROPERTY] },
            { events: [FLAG_CALLED], properties: [GLOBAL_PROPERTY] },
        ],
        ['keeps a matcher on all events', { events: [PAGEVIEW, ALL_EVENTS] }, { events: [ALL_EVENTS] }],
        [
            'counts every flag call when no matcher narrows the events',
            { properties: [GLOBAL_PROPERTY] },
            { properties: [GLOBAL_PROPERTY] },
        ],
        ['is null when no matcher can match a flag call', { events: [PAGEVIEW], actions: [ACTION] }, null],
        ['is null when only actions match', { actions: [ACTION] }, null],
    ])('%s', (_name, input, expected) => {
        expect(flagCallsOutsideEventsFilters(FLAG_EVALUATIONS_ONLY_TEAM, input)).toEqual(
            expected ? matchingFiltersToPropertyGroup(expected) : null
        )
    })

    it.each<[string, MatchingFiltersInput, boolean]>([
        ['only flag call matchers', { events: [FLAG_CALLED] }, true],
        ['a flag call and an action matcher', { events: [FLAG_CALLED], actions: [ACTION] }, false],
        ['no event matcher', { events: [], actions: [] }, false],
    ])('matches only flag calls: %s', (_name, input, expected) => {
        expect(matchesOnlyFlagCallsOutsideEvents(FLAG_EVALUATIONS_ONLY_TEAM, input)).toBe(expected)
    })

    it('adds flag call counts to the trends days they fall on', () => {
        const series = { data: [1, 2, 3], days: ['2026-10-15', '2026-10-16', '2026-10-17'], count: 6 }

        // The flag call query starts a day early, so a row before the first trends day is expected and dropped.
        const rows: [string, number][] = [
            ['2026-10-14', 100],
            ['2026-10-16', 10],
            ['2026-10-17', 5],
        ]

        expect(withFlagCallCounts(series, rows)).toEqual({ data: [1, 12, 8], count: 21 })
    })
})
