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
        // Filters: event property filters only, with or without a flag key
        ['no filters', { event_filters: [] }, null],
        [
            'a HogQL filter beside the flag key',
            {
                event_filters: [
                    FLAG_KEY_FILTER,
                    { key: "goe_0.properties.plan = 'pro'", type: PropertyFilterType.HogQL },
                ],
            },
            'filters',
        ],
    ])('%s', (_, overrides, expected) => {
        expect(flagCallCriterionProblem(flagCallCriterion(overrides))).toBe(expected)
    })
})
