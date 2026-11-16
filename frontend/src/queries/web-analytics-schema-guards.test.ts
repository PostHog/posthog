import { PropertyFilterType, PropertyOperator } from '~/types'

import { isCompareFilter, isWebAnalyticsPropertyFilters } from './web-analytics-schema-guards'

describe('web analytics schema guards', () => {
    it.each([
        [
            'event and session filters',
            [
                { type: PropertyFilterType.Event, key: '$pathname', operator: PropertyOperator.Exact, value: ['/'] },
                { type: PropertyFilterType.Session, key: '$channel_type', operator: PropertyOperator.IsSet },
            ],
            true,
        ],
        ['an empty list', [], true],
        [
            'an element filter, which web analytics does not support',
            [{ type: PropertyFilterType.Element, key: 'selector', operator: PropertyOperator.Exact, value: 'a' }],
            false,
        ],
        ['a filter with an unknown key', [{ type: 'event', key: 'x', operator: 'exact', extra: 1 }], false],
        ['a string from a hand-edited URL', 'not-a-list', false],
    ])('isWebAnalyticsPropertyFilters checks %s', (_name, data, expected) => {
        expect(isWebAnalyticsPropertyFilters(data)).toBe(expected)
    })

    it.each([
        [{ compare: true, compare_to: '-1w' }, true],
        [{}, true],
        [{ compare: 'yes' }, false],
        [{ compare: true, period: '-1w' }, false],
    ])('isCompareFilter(%j) is %s', (data, expected) => {
        expect(isCompareFilter(data)).toBe(expected)
    })
})
