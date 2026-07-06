import { BREAKDOWN_NULL_DISPLAY } from 'scenes/web-analytics/common'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { buildBreakdownPropertyFilter } from './ReplayButton'

describe('buildBreakdownPropertyFilter', () => {
    it.each([
        // Path keys with cleaning on must use IsCleanedPathExact, otherwise the cleaned display
        // value in the table (e.g. /blog/<id>) never matches the raw stored path (/blog/12345).
        ['$pathname', PropertyFilterType.Event, true, PropertyOperator.IsCleanedPathExact],
        ['$entry_pathname', PropertyFilterType.Session, true, PropertyOperator.IsCleanedPathExact],
        ['$end_pathname', PropertyFilterType.Session, true, PropertyOperator.IsCleanedPathExact],
        // Path keys with cleaning off stay exact
        ['$pathname', PropertyFilterType.Event, false, PropertyOperator.Exact],
        // Non-path keys stay exact even when cleaning is on
        ['$browser', PropertyFilterType.Event, true, PropertyOperator.Exact],
        ['$entry_utm_source', PropertyFilterType.Session, true, PropertyOperator.Exact],
    ] as const)('uses %s (%s, cleaning=%s) -> %s', (key, type, isPathCleaningEnabled, expectedOperator) => {
        const filter = buildBreakdownPropertyFilter(key, type, '/register', isPathCleaningEnabled)
        expect(filter).toEqual({ key, type, value: ['/register'], operator: expectedOperator })
    })

    it('returns IsNotSet for the (none) placeholder regardless of path cleaning', () => {
        const filter = buildBreakdownPropertyFilter('$pathname', PropertyFilterType.Event, BREAKDOWN_NULL_DISPLAY, true)
        expect(filter).toEqual({
            key: '$pathname',
            type: PropertyFilterType.Event,
            value: null,
            operator: PropertyOperator.IsNotSet,
        })
    })
})
