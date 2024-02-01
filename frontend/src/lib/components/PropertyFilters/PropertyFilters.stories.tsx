import { Meta } from '@storybook/react'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

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
            '/api/projects/:team_id/property_definitions*': {
                count: 4,
                next: null,
                previous: null,
                results: [
                    {
                        id: '017dde0e-1cb5-0000-68b4-44835b7c894k',
                        name: 'Browser',
                        is_numerical: false,
                        query_usage_30_day: null,
                        property_type: null,
                        is_seen_on_filtered_events: null,
                    },
                    {
                        id: '017dde0e-1cb5-0000-68b4-44835b7c894f',
                        name: 'OS',
                        is_numerical: false,
                        query_usage_30_day: null,
                        property_type: 'String',
                        is_seen_on_filtered_events: null,
                    },
                    {
                        id: '017dde0e-1cb5-0000-68b4-44835b7c894h',
                        name: '$timestamp',
                        is_numerical: false,
                        query_usage_30_day: null,
                        property_type: 'DateTime',
                        is_seen_on_filtered_events: null,
                    },
                ],
            },
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
