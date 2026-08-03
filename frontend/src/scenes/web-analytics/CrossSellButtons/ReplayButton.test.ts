import { PropertyFilterType, PropertyOperator } from '~/types'

import { buildUtmSourceFilters } from './ReplayButton'

describe('buildUtmSourceFilters', () => {
    it('filters on $entry_referring_domain and utm_source is_not_set for a "referrer:" display value', () => {
        // stats_table.py renders the source segment as "referrer:<domain>" when $entry_utm_source is
        // null but a referring domain exists — that display string is never a real property value.
        expect(buildUtmSourceFilters('referrer:news.ycombinator.com')).toEqual([
            {
                key: '$entry_referring_domain',
                type: PropertyFilterType.Session,
                value: ['news.ycombinator.com'],
                operator: PropertyOperator.Exact,
            },
            {
                key: '$entry_utm_source',
                type: PropertyFilterType.Session,
                value: null,
                operator: PropertyOperator.IsNotSet,
            },
        ])
    })

    it('filters on $entry_utm_source directly for a real utm_source value', () => {
        expect(buildUtmSourceFilters('google')).toEqual([
            {
                key: '$entry_utm_source',
                type: PropertyFilterType.Session,
                value: ['google'],
                operator: PropertyOperator.Exact,
            },
        ])
    })
})
