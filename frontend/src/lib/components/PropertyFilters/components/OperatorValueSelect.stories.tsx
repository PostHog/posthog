import React from 'react'
import { ComponentMeta } from '@storybook/react'
import { Provider } from 'kea'
import {
    OperatorValueSelect,
    OperatorValueSelectProps,
} from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { PropertyDefinition, PropertyType } from '~/types'

export default {
    title: 'Filters/PropertyFilters/OperatorValueSelect',
    Component: OperatorValueSelect,
} as ComponentMeta<typeof OperatorValueSelect>

const makePropertyDefinition = (name: string, propertyType: PropertyType | undefined): PropertyDefinition => ({
    id: name,
    name: name,
    property_type: propertyType,
    description: '',
    volume_30_day: null,
    query_usage_30_day: null,
})

const props = (type?: PropertyType | undefined): OperatorValueSelectProps => ({
    type: '',
    propkey: 'the_property',
    onChange: () => {},
    propertyDefinitions: [makePropertyDefinition('the_property', type)],
    defaultOpen: true,
})

export function OperatorValueWithStringProperty(): JSX.Element {
    return (
        <Provider>
            <h1>String Property</h1>
            <OperatorValueSelect {...props(PropertyType.String)} />
        </Provider>
    )
}

export function OperatorValueWithDateTimeProperty(): JSX.Element {
    return (
        <Provider>
            <h1>Date Time Property</h1>
            <OperatorValueSelect {...props(PropertyType.DateTime)} />
        </Provider>
    )
}

export function OperatorValueWithNumericProperty(): JSX.Element {
    return (
        <Provider>
            <h1>Numeric Property</h1>
            <OperatorValueSelect {...props(PropertyType.Numeric)} />
        </Provider>
    )
}

export function OperatorValueWithBooleanProperty(): JSX.Element {
    return (
        <Provider>
            <h1>Boolean Property</h1>
            <OperatorValueSelect {...props(PropertyType.Boolean)} />
        </Provider>
    )
}

export function OperatorValueWithUnknownProperty(): JSX.Element {
    return (
        <Provider>
            <h1>Property without specific type</h1>
            <OperatorValueSelect {...props()} />
        </Provider>
    )
}
