import { Meta } from '@storybook/react'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'

import { useStorybookMocks } from '~/mocks/browser'
import { AnyPropertyFilter, PropertyOperator } from '~/types'

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
    useStorybookMocks({
        get: {
            '/api/event/values/': [],
        },
    })
    return (
        <>
            <h1>Pop-over enabled</h1>
            <PropertyFilters
                propertyFilters={[...propertyFilters]}
                onChange={() => {}}
                pageKey="pageKey"
                showNestedArrow
                eventNames={[]}
            />
            <hr />
            <h1>Pop-over disabled</h1>
            <PropertyFilters
                propertyFilters={[...propertyFilters]}
                onChange={() => {}}
                pageKey="pageKey"
                eventNames={[]}
                disablePopover={true}
            />
        </>
    )
}

export function WithNoCloseButton(): JSX.Element {
    return <PropertyFiltersDisplay filters={[...propertyFilters]} />
}
