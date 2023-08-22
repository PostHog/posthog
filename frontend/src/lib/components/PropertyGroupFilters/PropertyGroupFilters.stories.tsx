import { useState } from 'react'
import { Meta } from '@storybook/react'
import { FilterLogicalOperator, FilterType, AnyPropertyFilter, PropertyGroupFilter, PropertyOperator } from '~/types'
import { useMountedLogic } from 'kea'
import { PropertyGroupFilters } from './PropertyGroupFilters'
import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { cohortsModel } from '~/models/cohortsModel'

const meta: Meta<typeof PropertyGroupFilters> = {
    title: 'Filters/PropertyGroupFilters',
    component: PropertyGroupFilters,
}
export default meta

const propertyFilters = [
    {
        key: '$timestamp',
        operator: PropertyOperator.IsDateAfter,
        type: 'event',
        value: '2020-04-01 12:34:56',
    },
    {
        key: 'Browser',
        operator: PropertyOperator.Exact,
        type: 'event',
        value: 'Chrome',
    },
] as AnyPropertyFilter[]

const taxonomicGroupTypes = [
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.EventFeatureFlags,
    TaxonomicFilterGroupType.Cohorts,
    TaxonomicFilterGroupType.Elements,
]

export function GroupPropertyFilters(): JSX.Element {
    useMountedLogic(cohortsModel)

    const [propertyGroupFilter, setPropertyGroupFilter] = useState<PropertyGroupFilter>({
        type: FilterLogicalOperator.And,
        values: [
            {
                type: FilterLogicalOperator.Or,
                values: propertyFilters,
            },
            {
                type: FilterLogicalOperator.And,
                values: propertyFilters,
            },
        ],
    })
    const [filters, setFilters] = useState<FilterType>({
        properties: propertyFilters,
    })

    return (
        <>
            <PropertyGroupFilters
                value={propertyGroupFilter}
                onChange={setPropertyGroupFilter}
                pageKey="page"
                taxonomicGroupTypes={taxonomicGroupTypes}
                // eventNames?: string[]
                setTestFilters={(f) => setFilters(f)}
                filters={filters}
                noTitle
            />
        </>
    )
}

export function EmptyGroupPropertyFilters(): JSX.Element {
    useMountedLogic(cohortsModel)

    const [propertyGroupFilter, setPropertyGroupFilter] = useState<PropertyGroupFilter>({
        type: FilterLogicalOperator.And,
        values: [],
    })
    const [filters, setFilters] = useState<FilterType>({})

    return (
        <>
            <PropertyGroupFilters
                value={propertyGroupFilter}
                onChange={setPropertyGroupFilter}
                pageKey="page-empty"
                taxonomicGroupTypes={taxonomicGroupTypes}
                // eventNames?: string[]
                setTestFilters={(f) => setFilters(f)}
                filters={filters}
                noTitle
            />
            <hr />
        </>
    )
}
