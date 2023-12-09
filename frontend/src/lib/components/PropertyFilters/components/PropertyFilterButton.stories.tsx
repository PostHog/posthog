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
    parameters: {
        testOptions: { include3000: true },
    },
}
export default meta

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

export function PseudoStates(): JSX.Element {
    return (
        <div className="border rounded p-2">
            <div>
                <h5>STATE=DEFAULT</h5>
                <PropertyFilterButton item={propertyFilters[0]} />
                <span className="ml-1" />
                <PropertyFilterButton item={propertyFilters[0]} onClose={() => {}} />
            </div>
            <div id="hover">
                <h5>STATE=HOVER</h5>
                <PropertyFilterButton item={propertyFilters[0]} />
                <span className="ml-1" />
                <PropertyFilterButton item={propertyFilters[0]} onClose={() => {}} />
            </div>
            <div id="active">
                <h5>STATE=HOVER,ACTIVE</h5>
                <PropertyFilterButton item={propertyFilters[0]} />
                <span className="ml-1" />
                <PropertyFilterButton item={propertyFilters[0]} onClose={() => {}} />
            </div>
        </div>
    )
}

PseudoStates.parameters = {
    pseudo: {
        hover: ['#hover .PropertyFilterButton', '#active .PropertyFilterButton'],
        active: ['#active .PropertyFilterButton'],
    },
}
