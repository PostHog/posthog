import { PropertyFilterType, PropertyOperator } from '~/types'

import { BREAKDOWN_NULL_DISPLAY, buildBreakdownPropertyFilter, exactMatchOperatorFor } from './common'

describe('common', () => {
    describe('exactMatchOperatorFor', () => {
        it.each([
            ['$pathname', PropertyFilterType.Event, false, PropertyOperator.Exact],
            ['$pathname', PropertyFilterType.Event, true, PropertyOperator.IsCleanedPathExact],
            ['$entry_pathname', PropertyFilterType.Session, true, PropertyOperator.IsCleanedPathExact],
            ['$initial_pathname', PropertyFilterType.Person, true, PropertyOperator.IsCleanedPathExact],
            ['$browser', PropertyFilterType.Event, true, PropertyOperator.Exact],
            ['$entry_utm_source', PropertyFilterType.Session, true, PropertyOperator.Exact],
        ])('%s (%s, cleaning: %s) uses %s', (key, type, doPathCleaning, expected) => {
            expect(exactMatchOperatorFor(key, type, doPathCleaning)).toBe(expected)
        })
    })

    describe('buildBreakdownPropertyFilter', () => {
        it('matches the unset property for the (none) breakdown row', () => {
            expect(buildBreakdownPropertyFilter('$pathname', PropertyFilterType.Event, BREAKDOWN_NULL_DISPLAY)).toEqual(
                {
                    key: '$pathname',
                    type: PropertyFilterType.Event,
                    value: null,
                    operator: PropertyOperator.IsNotSet,
                }
            )
        })

        it('exact-matches a plain path value', () => {
            expect(buildBreakdownPropertyFilter('$pathname', PropertyFilterType.Event, '/pricing')).toEqual({
                key: '$pathname',
                type: PropertyFilterType.Event,
                value: ['/pricing'],
                operator: PropertyOperator.Exact,
            })
        })

        it('cleans both sides when path cleaning is on', () => {
            expect(buildBreakdownPropertyFilter('$pathname', PropertyFilterType.Event, '/user/:id', true)).toEqual({
                key: '$pathname',
                type: PropertyFilterType.Event,
                value: ['/user/:id'],
                operator: PropertyOperator.IsCleanedPathExact,
            })
        })
    })
})
