import {
    withBehavioralCount,
    withBehavioralEventFilters,
    withBehavioralNegation,
} from 'lib/components/PropertyFilters/components/BehavioralPropertyFilterRow'

import {
    BehavioralEventType,
    BehavioralPropertyFilter,
    EventPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    TimeUnitType,
} from '~/types'

describe('BehavioralPropertyFilterRow value mapping', () => {
    const sourceIsWeb: EventPropertyFilter = {
        type: PropertyFilterType.Event,
        key: 'source',
        operator: PropertyOperator.Exact,
        value: ['web'],
    }

    // event_filters in the fixture prove count/negation edits leave nested filters untouched
    const counted: BehavioralPropertyFilter = {
        type: PropertyFilterType.Behavioral,
        key: 'signed_up',
        event_type: 'events',
        value: BehavioralEventType.PerformMultipleEvents,
        operator: PropertyOperator.GreaterThanOrEqual,
        operator_value: 3,
        time_value: 30,
        time_interval: TimeUnitType.Day,
        event_filters: [sourceIsWeb],
    }

    test.each<[string, PropertyOperator, number, Partial<BehavioralPropertyFilter>]>([
        [
            'at least 1 collapses to the plain criterion',
            PropertyOperator.GreaterThanOrEqual,
            1,
            { value: BehavioralEventType.PerformEvent, operator: undefined, operator_value: undefined },
        ],
        [
            'at least 3 keeps the count',
            PropertyOperator.GreaterThanOrEqual,
            3,
            {
                value: BehavioralEventType.PerformMultipleEvents,
                operator: PropertyOperator.GreaterThanOrEqual,
                operator_value: 3,
            },
        ],
        [
            'at most 1 is a count, not the plain criterion',
            PropertyOperator.LessThanOrEqual,
            1,
            {
                value: BehavioralEventType.PerformMultipleEvents,
                operator: PropertyOperator.LessThanOrEqual,
                operator_value: 1,
            },
        ],
    ])('%s', (_name, operator, operatorValue, expected) => {
        expect(withBehavioralCount(counted, operator, operatorValue)).toEqual({ ...counted, ...expected })
    })

    it('clears the count when switching to "did not perform"', () => {
        expect(withBehavioralNegation(counted, true)).toEqual({
            ...counted,
            negation: true,
            value: BehavioralEventType.PerformEvent,
            operator: undefined,
            operator_value: undefined,
        })
    })

    it('drops the negation when switching back to "performed"', () => {
        expect(withBehavioralNegation({ ...counted, negation: true }, false)).toEqual({
            ...counted,
            negation: undefined,
        })
    })

    it('replaces the nested event filters', () => {
        const emailIsSet: EventPropertyFilter = {
            type: PropertyFilterType.Event,
            key: 'email',
            operator: PropertyOperator.IsSet,
            value: null,
        }
        expect(withBehavioralEventFilters(counted, [emailIsSet])).toEqual({ ...counted, event_filters: [emailIsSet] })
    })

    it('drops event_filters entirely when the last nested filter is removed', () => {
        expect(withBehavioralEventFilters(counted, [])).toEqual({ ...counted, event_filters: undefined })
    })
})
