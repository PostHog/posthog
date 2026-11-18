import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'

import {
    BehavioralEventType,
    BehavioralLifecycleType,
    CohortCriteriaGroupFilter,
    CohortCriteriaType,
    CohortType,
    EventPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    TimeUnitType,
} from '~/types'

import {
    FlagCallCriterionProblem,
    cohortFlagCallProblem,
    flagCallCriterionProblem,
    moveNoticeProblem,
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
        // Window: a relative start at most 90 days back, with a month counted as 31 days
        ['90 days', { time_value: 90 }, null],
        ['91 days', { time_value: 91 }, 'window'],
        ['12 weeks', { time_value: 12, time_interval: TimeUnitType.Week }, null],
        ['13 weeks', { time_value: 13, time_interval: TimeUnitType.Week }, 'window'],
        ['2 months', { time_value: 2, time_interval: TimeUnitType.Month }, null],
        ['3 months', { time_value: 3, time_interval: TimeUnitType.Month }, 'window'],
        ['a year', { time_value: 1, time_interval: TimeUnitType.Year }, 'window'],
        ['an explicit start over a longer time value', { explicit_datetime: '-30d', time_value: 180 }, null],
        ['2160 hours', { explicit_datetime: '-2160h' }, null],
        ['2161 hours', { explicit_datetime: '-2161h' }, 'window'],
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

describe('moveNoticeProblem', () => {
    it.each<[string, Partial<CohortCriteriaType>, FlagCallCriterionProblem | null]>([
        ['a criterion that keeps counting every call', {}, null],
        ['a range past the limit', { time_value: 180 }, 'window'],
        ['a range past the limit on another event', { time_value: 180, key: '$pageview' }, null],
        [
            'a sequence step on the moving event',
            {
                key: '$pageview',
                value: BehavioralEventType.PerformSequenceEvents,
                seq_event: '$feature_flag_called',
                seq_event_type: TaxonomicFilterGroupType.Events,
            },
            'type',
        ],
    ])('%s', (_, overrides, expected) => {
        expect(moveNoticeProblem(flagCallCriterion(overrides))).toBe(expected)
    })
})

describe('cohortFlagCallProblem', () => {
    const and = (values: CohortCriteriaType[] | CohortCriteriaGroupFilter[]): CohortCriteriaGroupFilter => ({
        type: FilterLogicalOperator.And,
        values,
    })
    const dynamicCohort = (...groups: CohortCriteriaGroupFilter[]): CohortType => ({
        id: 1,
        is_static: false,
        groups: [],
        filters: { properties: { type: FilterLogicalOperator.Or, values: groups } },
    })
    const LONG_RANGE = flagCallCriterion({ time_value: 180 })

    it.each<[string, CohortType, FlagCallCriterionProblem | null]>([
        // flag_evaluations serves these, so the cohort keeps working after the move.
        ['a criterion flag_evaluations can serve', dynamicCohort(and([flagCallCriterion({})])), null],
        [
            'a range past the limit on another event',
            dynamicCohort(and([flagCallCriterion({ key: '$pageview', time_value: 180 })])),
            null,
        ],
        // These stop counting every call once new flag calls stop going to events.
        ['a range past the limit', dynamicCohort(and([LONG_RANGE])), 'window'],
        [
            'a sequence followed by $feature_flag_called',
            dynamicCohort(
                and([
                    flagCallCriterion({
                        key: '$pageview',
                        value: BehavioralEventType.PerformSequenceEvents,
                        seq_event: '$feature_flag_called',
                        seq_event_type: TaxonomicFilterGroupType.Events,
                    }),
                ])
            ),
            'type',
        ],
        [
            'a HogQL filter',
            dynamicCohort(
                and([flagCallCriterion({ event_filters: [{ key: '1 = 1', type: PropertyFilterType.HogQL }] })])
            ),
            'filters',
        ],
        // The API accepts groups nested deeper than the editor builds them.
        [
            'a problem in a nested group after a group without one',
            dynamicCohort(and([flagCallCriterion({})]), and([and([LONG_RANGE])])),
            'window',
        ],
        // A static cohort keeps the people it already has.
        ['static membership', { ...dynamicCohort(and([LONG_RANGE])), is_static: true }, null],
        // An experiment's exposure cohort counts the event on purpose. Its criterion belongs to the experiment.
        ['experiment exposure management', { ...dynamicCohort(and([LONG_RANGE])), experiment_set: [7] }, null],
    ])('%s', (_, cohort, expected) => {
        expect(cohortFlagCallProblem(cohort)).toBe(expected)
    })
})
