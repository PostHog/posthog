import { fireEvent, render } from '@testing-library/react'
import { Provider } from 'kea'
import posthog from 'posthog-js'
import { createElement } from 'react'

import {
    BehavioralPropertyFilterRow,
    withBehavioralCount,
    withBehavioralEventFilters,
    withBehavioralNegation,
} from 'lib/components/PropertyFilters/components/BehavioralPropertyFilterRow'

import { initKeaTests } from '~/test/init'
import {
    BehavioralEventType,
    BehavioralPropertyFilter,
    EventPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    TimeUnitType,
} from '~/types'

jest.mock('@posthog/lemon-ui', () => {
    const React = jest.requireActual('react')

    return {
        ...jest.requireActual('@posthog/lemon-ui'),
        LemonInput: ({ onChange, value, ...props }: any): JSX.Element =>
            React.createElement('input', {
                ...props,
                value,
                onChange: (event: { target: { value: string } }) => onChange(Number(event.target.value)),
            }),
        LemonSelect: ({ onChange, options, value, ...props }: any): JSX.Element =>
            React.createElement(
                'select',
                {
                    ...props,
                    value: String(value),
                    onChange: (event: { target: { value: string } }) =>
                        onChange(options.find((option: any) => String(option.value) === event.target.value)?.value),
                },
                options.map((option: any) =>
                    React.createElement(
                        'option',
                        { key: String(option.value), value: String(option.value) },
                        option.label
                    )
                )
            ),
    }
})

jest.mock('lib/components/TaxonomicPopover/TaxonomicPopover', () => {
    const React = jest.requireActual('react')

    return {
        TaxonomicPopover: ({ onChange, 'data-attr': dataAttr }: any): JSX.Element =>
            React.createElement('button', {
                'data-attr': dataAttr,
                onClick: () => onChange(42, 'actions'),
            }),
    }
})

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

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
    })

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

    it('captures each behavioral filter setting change without the selected event name', () => {
        const { container } = render(
            createElement(
                Provider,
                null,
                createElement(BehavioralPropertyFilterRow, {
                    filter: { ...counted, event_filters: undefined },
                    onChange: jest.fn(),
                    editable: true,
                    pageKey: 'test',
                })
            )
        )

        fireEvent.change(container.querySelector('[data-attr="behavioral-filter-negation"]')!, {
            target: { value: 'true' },
        })
        fireEvent.click(container.querySelector('[data-attr="behavioral-filter-event"]')!)
        fireEvent.change(container.querySelector('[data-attr="behavioral-filter-count-operator"]')!, {
            target: { value: PropertyOperator.LessThanOrEqual },
        })
        fireEvent.change(container.querySelector('[data-attr="behavioral-filter-count-value"]')!, {
            target: { value: '4' },
        })
        fireEvent.change(container.querySelector('[data-attr="behavioral-filter-time-value"]')!, {
            target: { value: '7' },
        })
        fireEvent.change(container.querySelector('[data-attr="behavioral-filter-time-interval"]')!, {
            target: { value: TimeUnitType.Week },
        })

        expect(posthog.capture).toHaveBeenCalledTimes(6)
        expect(posthog.capture).toHaveBeenNthCalledWith(1, 'behavioral filter behavior changed', {
            behavior: 'did_not_perform',
        })
        expect(posthog.capture).toHaveBeenNthCalledWith(2, 'behavioral filter event or action changed', {
            event_type: 'actions',
        })
        expect(posthog.capture).toHaveBeenNthCalledWith(3, 'behavioral filter count changed', {
            operator: PropertyOperator.LessThanOrEqual,
            operator_value: 3,
        })
        expect(posthog.capture).toHaveBeenNthCalledWith(4, 'behavioral filter count changed', {
            operator: PropertyOperator.GreaterThanOrEqual,
            operator_value: 4,
        })
        expect(posthog.capture).toHaveBeenNthCalledWith(5, 'behavioral filter time period changed', {
            time_value: 7,
            time_interval: TimeUnitType.Day,
        })
        expect(posthog.capture).toHaveBeenNthCalledWith(6, 'behavioral filter time period changed', {
            time_value: 30,
            time_interval: TimeUnitType.Week,
        })
    })
})
