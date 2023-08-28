import { Meta } from '@storybook/react'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { AnyPropertyFilter, PropertyOperator } from '~/types'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'

const meta: Meta<typeof PropertyFilters> = {
    title: 'Filters/PropertyFilters',
    component: PropertyFilters,
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
        value: ['Chrome', 'Safari', 'Edge', 'Opera'],
    },
    {
        key: 'OS',
        operator: PropertyOperator.Exact,
        type: 'event',
        value: ['MacOS', 'Windows'],
    },
] as AnyPropertyFilter[]

export function ComparingPropertyFilters(): JSX.Element {
    return (
        <>
            <h1>Pop-over enabled</h1>
            <PropertyFilters
                propertyFilters={[...propertyFilters]}
                onChange={() => {}}
                pageKey={'pageKey'}
                style={{ marginBottom: 0 }}
                showNestedArrow
                eventNames={[]}
            />
            <hr />
            <h1>Pop-over disabled</h1>
            <PropertyFilters
                propertyFilters={[...propertyFilters]}
                onChange={() => {}}
                pageKey={'pageKey'}
                style={{ marginBottom: 0 }}
                eventNames={[]}
                disablePopover={true}
            />
        </>
    )
}

export function WithNoCloseButton(): JSX.Element {
    return <PropertyFiltersDisplay filters={[...propertyFilters]} />
}
