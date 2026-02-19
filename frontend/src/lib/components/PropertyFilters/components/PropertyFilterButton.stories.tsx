import { Meta } from '@storybook/react'

import { AnyPropertyFilter, PropertyOperator } from '~/types'

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

const operatorVariants: { label: string; filter: AnyPropertyFilter }[] = [
    {
        label: 'Exact (multi)',
        filter: {
            key: 'Browser',
            operator: PropertyOperator.Exact,
            type: 'event',
            value: ['Chrome', 'Safari', 'Edge'],
        },
    },
    {
        label: 'Is not (multi)',
        filter: {
            key: 'Browser',
            operator: PropertyOperator.IsNot,
            type: 'event',
            value: ['Chrome', 'Safari', 'Edge'],
        },
    },
    {
        label: 'Contains',
        filter: { key: '$current_url', operator: PropertyOperator.IContains, type: 'event', value: 'checkout' },
    },
    {
        label: 'Does not contain',
        filter: { key: '$current_url', operator: PropertyOperator.NotIContains, type: 'event', value: 'checkout' },
    },
    {
        label: 'Matches regex',
        filter: { key: '$pathname', operator: PropertyOperator.Regex, type: 'event', value: '^/api/v[0-9]+' },
    },
    {
        label: 'Does not match regex',
        filter: { key: '$pathname', operator: PropertyOperator.NotRegex, type: 'event', value: '^/api/v[0-9]+' },
    },
    {
        label: 'Greater than',
        filter: { key: '$session_duration', operator: PropertyOperator.GreaterThan, type: 'event', value: 42 },
    },
    {
        label: 'Greater than or equal',
        filter: { key: '$session_duration', operator: PropertyOperator.GreaterThanOrEqual, type: 'event', value: 42 },
    },
    {
        label: 'Less than',
        filter: { key: '$session_duration', operator: PropertyOperator.LessThan, type: 'event', value: 42 },
    },
    {
        label: 'Less than or equal',
        filter: { key: '$session_duration', operator: PropertyOperator.LessThanOrEqual, type: 'event', value: 42 },
    },
    { label: 'Between', filter: { key: 'score', operator: PropertyOperator.Between, type: 'event', value: [10, 100] } },
    {
        label: 'Not between',
        filter: { key: 'score', operator: PropertyOperator.NotBetween, type: 'event', value: [10, 100] },
    },
    {
        label: 'Is date exact',
        filter: { key: '$timestamp', operator: PropertyOperator.IsDateExact, type: 'event', value: '2024-06-15' },
    },
    {
        label: 'Is date before',
        filter: { key: '$timestamp', operator: PropertyOperator.IsDateBefore, type: 'event', value: '2024-06-15' },
    },
    {
        label: 'Is date after',
        filter: { key: '$timestamp', operator: PropertyOperator.IsDateAfter, type: 'event', value: '2024-06-15' },
    },
    { label: 'Is set', filter: { key: 'email', operator: PropertyOperator.IsSet, type: 'event', value: 'is_set' } },
    {
        label: 'Is not set',
        filter: { key: 'email', operator: PropertyOperator.IsNotSet, type: 'event', value: 'is_not_set' },
    },
]

export function OperatorVariants(): JSX.Element {
    return (
        <div className="space-y-2">
            {operatorVariants.map(({ label, filter }) => (
                <div key={filter.operator}>
                    <div className="text-xs font-bold mb-1">{label}</div>
                    <PropertyFilterButton item={filter} />
                </div>
            ))}
        </div>
    )
}
