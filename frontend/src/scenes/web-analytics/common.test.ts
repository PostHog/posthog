import { PropertyFilterType, PropertyOperator } from '~/types'

import { exactMatchOperatorFor } from './common'

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
