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

const operatorGroups: { name: string; filters: AnyPropertyFilter[] }[] = [
    {
        name: 'Multi-value (Exact / Is not)',
        filters: [
            { key: 'Browser', operator: PropertyOperator.Exact, type: 'event', value: ['Chrome', 'Safari', 'Edge'] },
            { key: 'Browser', operator: PropertyOperator.IsNot, type: 'event', value: ['Chrome', 'Safari', 'Edge'] },
        ] as AnyPropertyFilter[],
    },
    {
        name: 'Text contains',
        filters: [
            { key: '$current_url', operator: PropertyOperator.IContains, type: 'event', value: 'checkout' },
            { key: '$current_url', operator: PropertyOperator.NotIContains, type: 'event', value: 'checkout' },
        ] as AnyPropertyFilter[],
    },
    {
        name: 'Regex',
        filters: [
            { key: '$pathname', operator: PropertyOperator.Regex, type: 'event', value: '^/api/v[0-9]+' },
            { key: '$pathname', operator: PropertyOperator.NotRegex, type: 'event', value: '^/api/v[0-9]+' },
        ] as AnyPropertyFilter[],
    },
    {
        name: 'Numeric comparison',
        filters: [
            { key: '$session_duration', operator: PropertyOperator.GreaterThan, type: 'event', value: 42 },
            { key: '$session_duration', operator: PropertyOperator.GreaterThanOrEqual, type: 'event', value: 42 },
            { key: '$session_duration', operator: PropertyOperator.LessThan, type: 'event', value: 42 },
            { key: '$session_duration', operator: PropertyOperator.LessThanOrEqual, type: 'event', value: 42 },
        ] as AnyPropertyFilter[],
    },
    {
        name: 'Between',
        filters: [
            { key: 'score', operator: PropertyOperator.Between, type: 'event', value: [10, 100] },
            { key: 'score', operator: PropertyOperator.NotBetween, type: 'event', value: [10, 100] },
        ] as AnyPropertyFilter[],
    },
    {
        name: 'Date',
        filters: [
            { key: '$timestamp', operator: PropertyOperator.IsDateExact, type: 'event', value: '2024-06-15' },
            { key: '$timestamp', operator: PropertyOperator.IsDateBefore, type: 'event', value: '2024-06-15' },
            { key: '$timestamp', operator: PropertyOperator.IsDateAfter, type: 'event', value: '2024-06-15' },
        ] as AnyPropertyFilter[],
    },
    {
        name: 'Set / Not set',
        filters: [
            { key: 'email', operator: PropertyOperator.IsSet, type: 'event', value: 'is_set' },
            { key: 'email', operator: PropertyOperator.IsNotSet, type: 'event', value: 'is_not_set' },
        ] as AnyPropertyFilter[],
    },
]

export function OperatorVariantsEditing(): JSX.Element {
    useStorybookMocks({ get: { '/api/event/values/': [] } })
    return (
        <div className="space-y-6">
            {operatorGroups.map(({ name, filters: groupFilters }) => (
                <div key={name}>
                    <h3>{name}</h3>
                    <PropertyFilters
                        propertyFilters={[...groupFilters]}
                        onChange={() => {}}
                        pageKey={`operator-variants-${name}`}
                        eventNames={[]}
                        disablePopover={true}
                    />
                </div>
            ))}
        </div>
    )
}
