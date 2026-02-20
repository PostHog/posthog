import { Meta } from '@storybook/react'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'

import { useStorybookMocks } from '~/mocks/browser'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

const meta: Meta<typeof PropertyFilters> = {
    title: 'Filters/PropertyFilters',
    component: PropertyFilters,
}
export default meta

const propertyFilters = [
    {
        key: '$timestamp',
        operator: PropertyOperator.IsDateAfter,
        type: PropertyFilterType.Event,
        value: '2020-04-01 12:34:56',
    },
    {
        key: 'Browser',
        operator: PropertyOperator.Exact,
        type: PropertyFilterType.Event,
        value: ['Chrome', 'Safari', 'Edge', 'Opera'],
    },
    {
        key: 'OS',
        operator: PropertyOperator.Exact,
        type: PropertyFilterType.Event,
        value: ['MacOS', 'Windows'],
    },
] satisfies AnyPropertyFilter[]

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

const operatorGroups = [
    {
        id: 'multi-value',
        name: 'Multi-value (Exact / Is not)',
        filters: [
            {
                key: 'Browser',
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
                value: ['Chrome', 'Safari', 'Edge'],
            },
            {
                key: 'Browser',
                operator: PropertyOperator.IsNot,
                type: PropertyFilterType.Event,
                value: ['Chrome', 'Safari', 'Edge'],
            },
        ] satisfies AnyPropertyFilter[],
    },
    {
        id: 'text-contains',
        name: 'Text contains',
        filters: [
            {
                key: '$current_url',
                operator: PropertyOperator.IContains,
                type: PropertyFilterType.Event,
                value: 'checkout',
            },
            {
                key: '$current_url',
                operator: PropertyOperator.NotIContains,
                type: PropertyFilterType.Event,
                value: 'checkout',
            },
        ] satisfies AnyPropertyFilter[],
    },
    {
        id: 'regex',
        name: 'Regex',
        filters: [
            {
                key: '$pathname',
                operator: PropertyOperator.Regex,
                type: PropertyFilterType.Event,
                value: '^/api/v[0-9]+',
            },
            {
                key: '$pathname',
                operator: PropertyOperator.NotRegex,
                type: PropertyFilterType.Event,
                value: '^/api/v[0-9]+',
            },
        ] satisfies AnyPropertyFilter[],
    },
    {
        id: 'numeric-comparison',
        name: 'Numeric comparison',
        filters: [
            {
                key: '$session_duration',
                operator: PropertyOperator.GreaterThan,
                type: PropertyFilterType.Event,
                value: 42,
            },
            {
                key: '$session_duration',
                operator: PropertyOperator.GreaterThanOrEqual,
                type: PropertyFilterType.Event,
                value: 42,
            },
            {
                key: '$session_duration',
                operator: PropertyOperator.LessThan,
                type: PropertyFilterType.Event,
                value: 42,
            },
            {
                key: '$session_duration',
                operator: PropertyOperator.LessThanOrEqual,
                type: PropertyFilterType.Event,
                value: 42,
            },
        ] satisfies AnyPropertyFilter[],
    },
    {
        id: 'between',
        name: 'Between',
        filters: [
            { key: 'score', operator: PropertyOperator.Between, type: PropertyFilterType.Event, value: [10, 100] },
            { key: 'score', operator: PropertyOperator.NotBetween, type: PropertyFilterType.Event, value: [10, 100] },
        ] satisfies AnyPropertyFilter[],
    },
    {
        id: 'date',
        name: 'Date',
        filters: [
            {
                key: '$timestamp',
                operator: PropertyOperator.IsDateExact,
                type: PropertyFilterType.Event,
                value: '2024-06-15',
            },
            {
                key: '$timestamp',
                operator: PropertyOperator.IsDateBefore,
                type: PropertyFilterType.Event,
                value: '2024-06-15',
            },
            {
                key: '$timestamp',
                operator: PropertyOperator.IsDateAfter,
                type: PropertyFilterType.Event,
                value: '2024-06-15',
            },
        ] satisfies AnyPropertyFilter[],
    },
    {
        id: 'set-not-set',
        name: 'Set / Not set',
        filters: [
            { key: 'email', operator: PropertyOperator.IsSet, type: PropertyFilterType.Event, value: 'is_set' },
            { key: 'email', operator: PropertyOperator.IsNotSet, type: PropertyFilterType.Event, value: 'is_not_set' },
        ] satisfies AnyPropertyFilter[],
    },
]

export function OperatorVariantsEditing(): JSX.Element {
    useStorybookMocks({ get: { '/api/event/values/': [] } })
    return (
        <div className="space-y-6">
            {operatorGroups.map(({ id, name, filters: groupFilters }) => (
                <div key={id}>
                    <h3>{name}</h3>
                    <PropertyFilters
                        propertyFilters={[...groupFilters]}
                        onChange={() => {}}
                        pageKey={`operator-variants-${id}`}
                        eventNames={[]}
                        disablePopover={true}
                    />
                </div>
            ))}
        </div>
    )
}
