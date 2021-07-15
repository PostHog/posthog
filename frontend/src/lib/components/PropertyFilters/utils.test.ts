import { EmptyPropertyFilter, PropertyFilter, PropertyOperator } from '../../../types'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'

describe('isValidPropertyFilter()', () => {
    it('returns values correctly', () => {
        const emptyProperty: EmptyPropertyFilter = {}
        const realProperty: PropertyFilter = {
            key: 'angular',
            value: 'bla',
            type: 'cohort',
            operator: PropertyOperator.LessThan,
        }
        expect(isValidPropertyFilter(emptyProperty)).toEqual(false)
        expect(isValidPropertyFilter(realProperty)).toEqual(true)
        expect(isValidPropertyFilter(undefined as any)).toEqual(false)
        expect(isValidPropertyFilter(null as any)).toEqual(false)
        expect(isValidPropertyFilter({ bla: 'true' } as any)).toEqual(false)
        expect(isValidPropertyFilter({ key: undefined })).toEqual(false)
        expect(isValidPropertyFilter({ key: 'cohort', value: 123 })).toEqual(true)
    })
})
