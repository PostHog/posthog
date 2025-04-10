import {
    breakdownFilterToTaxonomicFilterType,
    convertPropertiesToPropertyGroup,
    convertPropertyGroupToProperties,
    isValidPropertyFilter,
    propertyFilterTypeToTaxonomicFilterType,
} from 'lib/components/PropertyFilters/utils'

import { BreakdownFilter } from '~/queries/schema/schema-general'

import {
    AnyPropertyFilter,
    CohortPropertyFilter,
    ElementPropertyFilter,
    EmptyPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyGroupFilter,
    PropertyOperator,
    SessionPropertyFilter,
} from '../../../types'
import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'

describe('isValidPropertyFilter()', () => {
    it('returns values correctly', () => {
        const emptyProperty: AnyPropertyFilter = {} as EmptyPropertyFilter
        const realProperty: CohortPropertyFilter = {
            key: 'id',
            value: 33,
            type: PropertyFilterType.Cohort,
            operator: PropertyOperator.NotIn,
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
            propertyFilterTypeToTaxonomicFilterType({
                type: PropertyFilterType.Cohort,
                operator: PropertyOperator.In,
                key: 'id',
                value: 33,
            })
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
        ).toEqual(TaxonomicFilterGroupType.SessionProperties)
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
            TaxonomicFilterGroupType.SessionProperties
        )
        expect(breakdownFilterToTaxonomicFilterType({ ...baseFilter, breakdown_type: 'hogql' })).toEqual(
            TaxonomicFilterGroupType.HogQLExpression
        )
    })
})

describe('convertPropertyGroupToProperties()', () => {
    it('converts a single layer property group into an array of properties', () => {
        const propertyGroup = {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        { key: '$browser', type: PropertyFilterType.Event, operator: PropertyOperator.IsSet },
                        { key: '$current_url', type: PropertyFilterType.Event, operator: PropertyOperator.IsSet },
                    ] as AnyPropertyFilter[],
                },
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        { key: '$lib', type: PropertyFilterType.Event, operator: PropertyOperator.IsSet },
                    ] as AnyPropertyFilter[],
                },
            ],
        }
        expect(convertPropertyGroupToProperties(propertyGroup)).toEqual([
            { key: '$browser', type: PropertyFilterType.Event, operator: PropertyOperator.IsSet },
            { key: '$current_url', type: PropertyFilterType.Event, operator: PropertyOperator.IsSet },
            { key: '$lib', type: PropertyFilterType.Event, operator: PropertyOperator.IsSet },
        ])
    })

    it('converts a deeply nested property group into an array of properties', () => {
        const propertyGroup: PropertyGroupFilter = {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [{ type: FilterLogicalOperator.And, values: [{ key: '$lib' } as any] }],
                },
                { type: FilterLogicalOperator.And, values: [{ key: '$browser' } as any] },
            ],
        }
        expect(convertPropertyGroupToProperties(propertyGroup)).toEqual([{ key: '$lib' }, { key: '$browser' }])
    })
})

describe('convertPropertiesToPropertyGroup', () => {
    it('converts properties to one AND operator property group', () => {
        const properties: any[] = [{ key: '$lib' }, { key: '$browser' }, { key: '$current_url' }]
        expect(convertPropertiesToPropertyGroup(properties)).toEqual({
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [{ key: '$lib' }, { key: '$browser' }, { key: '$current_url' }],
                },
            ],
        })
    })

    it('converts undefined properties to one AND operator property group', () => {
        expect(convertPropertiesToPropertyGroup(undefined)).toEqual({
            type: FilterLogicalOperator.And,
            values: [],
        })
    })
})
