import {
    AnyPropertyFilter,
    CohortPropertyFilter,
    ElementPropertyFilter,
    EmptyPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    SessionPropertyFilter,
} from '../../../types'
import {
    isValidPropertyFilter,
    propertyFilterTypeToTaxonomicFilterType,
    breakdownFilterToTaxonomicFilterType,
} from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { BreakdownFilter } from '~/queries/schema'

describe('isValidPropertyFilter()', () => {
    it('returns values correctly', () => {
        const emptyProperty: AnyPropertyFilter = {} as EmptyPropertyFilter
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
        expect(isValidPropertyFilter({ key: undefined } as any)).toEqual(false)
        expect(isValidPropertyFilter({ key: 'cohort', value: 123 } as any)).toEqual(true)
    })
})

describe('propertyFilterTypeToTaxonomicFilterType()', () => {
    const baseFilter: AnyPropertyFilter = {
        type: PropertyFilterType.Event,
        key: 'some_key',
        value: 'some_value',
        operator: PropertyOperator.Exact,
    }

    it('returns values correctly', () => {
        expect(propertyFilterTypeToTaxonomicFilterType({} as EmptyPropertyFilter)).toEqual(undefined)
        expect(
            propertyFilterTypeToTaxonomicFilterType({ type: PropertyFilterType.Cohort, key: 'id', value: 33 })
        ).toEqual(TaxonomicFilterGroupType.Cohorts)
        expect(
            propertyFilterTypeToTaxonomicFilterType({
                ...baseFilter,
                type: PropertyFilterType.Group,
                group_type_index: 2,
            })
        ).toEqual('groups_2')
        expect(
            propertyFilterTypeToTaxonomicFilterType({
                ...baseFilter,
                type: PropertyFilterType.Event,
                key: '$feature/abc',
            })
        ).toEqual(TaxonomicFilterGroupType.EventFeatureFlags)
        expect(propertyFilterTypeToTaxonomicFilterType({ ...baseFilter, type: PropertyFilterType.Person })).toEqual(
            TaxonomicFilterGroupType.PersonProperties
        )
        expect(propertyFilterTypeToTaxonomicFilterType({ ...baseFilter, type: PropertyFilterType.Event })).toEqual(
            TaxonomicFilterGroupType.EventProperties
        )
        expect(
            propertyFilterTypeToTaxonomicFilterType({
                ...baseFilter,
                type: PropertyFilterType.Element,
            } as ElementPropertyFilter)
        ).toEqual(TaxonomicFilterGroupType.Elements)
        expect(
            propertyFilterTypeToTaxonomicFilterType({
                ...baseFilter,
                type: PropertyFilterType.Session,
            } as SessionPropertyFilter)
        ).toEqual(TaxonomicFilterGroupType.Sessions)
        expect(propertyFilterTypeToTaxonomicFilterType({ ...baseFilter, type: PropertyFilterType.HogQL })).toEqual(
            TaxonomicFilterGroupType.HogQLExpression
        )
    })
})

describe('breakdownFilterToTaxonomicFilterType()', () => {
    const baseFilter: BreakdownFilter = {
        breakdown_type: 'event',
        breakdown: '$browser',
    }

    it('returns values correctly', () => {
        expect(breakdownFilterToTaxonomicFilterType({} as BreakdownFilter)).toEqual(undefined)
        expect(breakdownFilterToTaxonomicFilterType({ breakdown_type: 'cohort', breakdown: 33 })).toEqual(
            TaxonomicFilterGroupType.Cohorts
        )
        expect(
            breakdownFilterToTaxonomicFilterType({
                ...baseFilter,
                breakdown_type: 'group',
                breakdown_group_type_index: 2,
            })
        ).toEqual('groups_2')
        expect(
            breakdownFilterToTaxonomicFilterType({
                ...baseFilter,
                breakdown_type: 'event',
                breakdown: '$feature/abc',
            })
        ).toEqual(TaxonomicFilterGroupType.EventFeatureFlags)
        expect(breakdownFilterToTaxonomicFilterType({ ...baseFilter, breakdown_type: 'person' })).toEqual(
            TaxonomicFilterGroupType.PersonProperties
        )
        expect(breakdownFilterToTaxonomicFilterType({ ...baseFilter, breakdown_type: 'event' })).toEqual(
            TaxonomicFilterGroupType.EventProperties
        )
        expect(breakdownFilterToTaxonomicFilterType({ ...baseFilter, breakdown_type: 'session' })).toEqual(
            TaxonomicFilterGroupType.Sessions
        )
        expect(breakdownFilterToTaxonomicFilterType({ ...baseFilter, breakdown_type: 'hogql' })).toEqual(
            TaxonomicFilterGroupType.HogQLExpression
        )
    })
})
