import React from 'react'
import { ComponentMeta } from '@storybook/react'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { Provider } from 'kea'
import { PropertyFilter, PropertyOperator } from '~/types'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'

export default {
    title: 'PostHog/Components/PropertyFilters',
    Component: PropertyFilters,
} as ComponentMeta<typeof PropertyFilters>

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
] as PropertyFilter[]

export const ComparingPropertyFilters = (): JSX.Element => (
    <Provider>
        <h1>Pop-over enabled</h1>
        <PropertyFilters
            propertyFilters={[...propertyFilters]}
            onChange={() => {}}
            pageKey={'pageKey'}
            style={{ marginBottom: 0 }}
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
    </Provider>
)

export const WithNoCloseButton = (): JSX.Element => (
    <Provider>
        <PropertyFiltersDisplay filters={[...propertyFilters]} />
    </Provider>
)
