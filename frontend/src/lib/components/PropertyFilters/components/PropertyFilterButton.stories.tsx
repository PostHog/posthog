import { Meta } from '@storybook/react'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { PropertyFilterButton } from './PropertyFilterButton'

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
    {
        key: 'OS',
        operator: PropertyOperator.IsNot,
        type: 'person',
        value: ['MacOS', 'Windows'],
    },
    {
        key: 'text',
        value: ['my value'],
        operator: 'exact',
        type: 'element',
    },
    {
        key: '$session_duration',
        value: 10,
        operator: 'gt',
        type: 'session',
    },
    {
        key: 'id',
        value: 50001,
        type: 'cohort',
    },
    {
        type: 'hogql',
        key: 'properties.$current_url',
        value: null,
    },
    {
        key: '$feature/surveys',
        value: ['true'],
        operator: 'exact',
        type: 'event',
    },
    {
        key: 'organization_id',
        value: ['123'],
        operator: 'exact',
        type: 'group',
        group_type_index: 0,
    },
    {
        type: 'recording',
        key: 'duration',
        value: 10,
        operator: 'gt',
    },
    {},
] as AnyPropertyFilter[]

const meta: Meta<typeof PropertyFilterButton> = {
    title: 'Filters/Property Filter Button',
    component: PropertyFilterButton,
    tags: ['autodocs'],
}
export default meta

export function Button(): JSX.Element {
    return <PropertyFilterButton item={propertyFilters[0]} onClick={() => {}} onClose={() => {}} />
}

export function FilterTypes(): JSX.Element {
    return (
        <div>
            {propertyFilters.map((f) => (
                <div className="mb-1" key={f.type && f.key ? `${f.type}_${f.key}` : 'empty-property-filter'}>
                    <PropertyFilterButton item={f} />
                </div>
            ))}
        </div>
    )
}

const operatorVariantFilters = [
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
    { key: '$current_url', operator: PropertyOperator.IContains, type: PropertyFilterType.Event, value: 'checkout' },
    { key: '$current_url', operator: PropertyOperator.NotIContains, type: PropertyFilterType.Event, value: 'checkout' },
    { key: '$pathname', operator: PropertyOperator.Regex, type: PropertyFilterType.Event, value: '^/api/v[0-9]+' },
    { key: '$pathname', operator: PropertyOperator.NotRegex, type: PropertyFilterType.Event, value: '^/api/v[0-9]+' },
    { key: '$session_duration', operator: PropertyOperator.GreaterThan, type: PropertyFilterType.Event, value: 42 },
    {
        key: '$session_duration',
        operator: PropertyOperator.GreaterThanOrEqual,
        type: PropertyFilterType.Event,
        value: 42,
    },
    { key: '$session_duration', operator: PropertyOperator.LessThan, type: PropertyFilterType.Event, value: 42 },
    { key: '$session_duration', operator: PropertyOperator.LessThanOrEqual, type: PropertyFilterType.Event, value: 42 },
    { key: 'score', operator: PropertyOperator.Between, type: PropertyFilterType.Event, value: [10, 100] },
    { key: 'score', operator: PropertyOperator.NotBetween, type: PropertyFilterType.Event, value: [10, 100] },
    { key: '$timestamp', operator: PropertyOperator.IsDateExact, type: PropertyFilterType.Event, value: '2024-06-15' },
    { key: '$timestamp', operator: PropertyOperator.IsDateBefore, type: PropertyFilterType.Event, value: '2024-06-15' },
    { key: '$timestamp', operator: PropertyOperator.IsDateAfter, type: PropertyFilterType.Event, value: '2024-06-15' },
    { key: 'email', operator: PropertyOperator.IsSet, type: PropertyFilterType.Event, value: 'is_set' },
    { key: 'email', operator: PropertyOperator.IsNotSet, type: PropertyFilterType.Event, value: 'is_not_set' },
] satisfies AnyPropertyFilter[]

export function OperatorVariants(): JSX.Element {
    return (
        <div className="space-y-2">
            {operatorVariantFilters.map((filter, index) => (
                <div key={index}>
                    <PropertyFilterButton item={filter} />
                </div>
            ))}
        </div>
    )
}
