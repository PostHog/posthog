import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'

import {
    BehavioralEventType,
    BehavioralLifecycleType,
    CohortCriteriaType,
    EventPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    TimeUnitType,
} from '~/types'

import {
    FlagCallCriterionProblem,
    flagCallCriterionProblem,
} from 'products/cohorts/frontend/criteria/flagCallCriterionProblem'

const FLAG_KEY_FILTER: EventPropertyFilter = {
    key: '$feature_flag',
    type: PropertyFilterType.Event,
    operator: PropertyOperator.Exact,
    value: 'beta-feature',
}

function flagCallCriterion(overrides: Partial<CohortCriteriaType>): CohortCriteriaType {
    return {
        id: 'criterion',
        key: '$feature_flag_called',
        type: BehavioralFilterKey.Behavioral,
        event_type: TaxonomicFilterGroupType.Events,
        value: BehavioralEventType.PerformEvent,
        time_value: 30,
        time_interval: TimeUnitType.Day,
        event_filters: [FLAG_KEY_FILTER],
        ...overrides,
    }
}

describe('flagCallCriterionProblem', () => {
    it.each<[string, Partial<CohortCriteriaType>, FlagCallCriterionProblem | null]>([
        // Type
        ['completed event', {}, null],
        ['did not complete event', { negation: true }, null],
        ['completed an event multiple times', { value: BehavioralEventType.PerformMultipleEvents }, null],
        ['a sequence', { value: BehavioralEventType.PerformSequenceEvents }, 'type'],
        ['completed an event for the first time', { value: BehavioralLifecycleType.PerformEventFirstTime }, 'type'],
        // Window: a relative start at most 88 days back, with a month counted as 31 days
        ['88 days', { time_value: 88 }, null],
        ['89 days', { time_value: 89 }, 'window'],
        ['12 weeks', { time_value: 12, time_interval: TimeUnitType.Week }, null],
        ['13 weeks', { time_value: 13, time_interval: TimeUnitType.Week }, 'window'],
        ['2 months', { time_value: 2, time_interval: TimeUnitType.Month }, null],
        ['3 months', { time_value: 3, time_interval: TimeUnitType.Month }, 'window'],
        ['a year', { time_value: 1, time_interval: TimeUnitType.Year }, 'window'],
        ['an explicit start over a longer time value', { explicit_datetime: '-30d', time_value: 180 }, null],
        ['2112 hours', { explicit_datetime: '-2112h' }, null],
        ['2113 hours', { explicit_datetime: '-2113h' }, 'window'],
        ['an absolute start', { explicit_datetime: '2026-09-01' }, 'window'],
        ['no window', { time_value: null, time_interval: null }, 'window'],
        // Flag key: an equals filter on $feature_flag, and event property filters only
        ['no filters', { event_filters: [] }, 'flag-key'],
        ['several flag keys', { event_filters: [{ ...FLAG_KEY_FILTER, value: ['beta-feature', 'new-nav'] }] }, null],
        ['an empty flag key', { event_filters: [{ ...FLAG_KEY_FILTER, value: '' }] }, 'flag-key'],
        [
            'several flag keys with one empty',
            { event_filters: [{ ...FLAG_KEY_FILTER, value: ['beta-feature', ''] }] },
            'flag-key',
        ],
        // The rewrite refuses a key that parses as JSON, including what only Python's json.loads reads
        ['a flag key that reads as a number', { event_filters: [{ ...FLAG_KEY_FILTER, value: '100' }] }, 'flag-key'],
        ['a flag key that reads as null', { event_filters: [{ ...FLAG_KEY_FILTER, value: 'null' }] }, 'flag-key'],
        ['a flag key that reads as NaN', { event_filters: [{ ...FLAG_KEY_FILTER, value: 'NaN' }] }, 'flag-key'],
        [
            'a flag key filter with no operator',
            {
                event_filters: [
                    {
                        key: '$feature_flag',
                        type: PropertyFilterType.Event,
                        value: 'beta-feature',
                    } as EventPropertyFilter,
                ],
            },
            null,
        ],
        [
            'a flag key that is contained rather than equal',
            { event_filters: [{ ...FLAG_KEY_FILTER, operator: PropertyOperator.IContains }] },
            'flag-key',
        ],
        [
            'another event property beside the flag key',
            {
                event_filters: [
                    FLAG_KEY_FILTER,
                    {
                        key: '$browser',
                        type: PropertyFilterType.Event,
                        operator: PropertyOperator.Exact,
                        value: 'Chrome',
                    },
                ],
            },
            null,
        ],
        [
            'a HogQL filter beside the flag key',
            { event_filters: [FLAG_KEY_FILTER, { key: "$window_id = 'w'", type: PropertyFilterType.HogQL }] },
            'flag-key',
        ],
    ])('%s', (_, overrides, expected) => {
        expect(flagCallCriterionProblem(flagCallCriterion(overrides))).toBe(expected)
    })
})
