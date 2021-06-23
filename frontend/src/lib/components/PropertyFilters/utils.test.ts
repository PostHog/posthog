import { EmptyPropertyFilter, PropertyFilter, PropertyOperator } from '../../../types'
import { isFilledPropertyFilter } from 'lib/components/PropertyFilters/utils'

describe('isFilledPropertyFilter()', () => {
    it('returns values correctly', () => {
        const emptyProperty: EmptyPropertyFilter = {}
        const realProperty: PropertyFilter = {
            key: 'angular',
            value: 'bla',
            type: 'cohort',
            operator: PropertyOperator.LessThan,
        }
        expect(isFilledPropertyFilter(emptyProperty)).toEqual(false)
        expect(isFilledPropertyFilter(realProperty)).toEqual(true)
        expect(isFilledPropertyFilter(undefined as any)).toEqual(false)
        expect(isFilledPropertyFilter(null as any)).toEqual(false)
        expect(isFilledPropertyFilter({ bla: 'true' } as any)).toEqual(false)
        expect(isFilledPropertyFilter({ key: undefined })).toEqual(false)
        expect(isFilledPropertyFilter({ key: 'cohort', value: 123 })).toEqual(true)
    })
})
