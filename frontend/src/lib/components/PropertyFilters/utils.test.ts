import { AnyPropertyFilter, CohortPropertyFilter, PropertyFilterType } from '../../../types'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'

describe('isValidPropertyFilter()', () => {
    it('returns values correctly', () => {
        const emptyProperty: AnyPropertyFilter = {}
        const realProperty: CohortPropertyFilter = {
            key: 'id',
            value: 33,
            type: PropertyFilterType.Cohort,
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
