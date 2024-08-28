import { Meta } from '@storybook/react'
import {
    OperatorValueSelect,
    OperatorValueSelectProps,
} from 'lib/components/PropertyFilters/components/OperatorValueSelect'

import { PropertyDefinition, PropertyType } from '~/types'

const meta: Meta<typeof OperatorValueSelect> = {
    title: 'Filters/PropertyFilters/OperatorValueSelect',
    component: OperatorValueSelect,
}
export default meta

const makePropertyDefinition = (name: string, propertyType: PropertyType | undefined): PropertyDefinition => ({
    id: name,
    name: name,
    property_type: propertyType,
    description: '',
})

const props = (type?: PropertyType | undefined): OperatorValueSelectProps => ({
    type: undefined,
    propertyKey: 'the_property',
    onChange: () => {},
    propertyDefinitions: [makePropertyDefinition('the_property', type)],
    defaultOpen: true,
})

export function OperatorValueWithStringProperty(): JSX.Element {
    return (
        <>
            <h1>String Property</h1>
            <OperatorValueSelect {...props(PropertyType.String)} />
        </>
    )
}

export function OperatorValueWithDateTimeProperty(): JSX.Element {
    return (
        <>
            <h1>Date Time Property</h1>
            <OperatorValueSelect {...props(PropertyType.DateTime)} />
        </>
    )
}

export function OperatorValueWithNumericProperty(): JSX.Element {
    return (
        <>
            <h1>Numeric Property</h1>
            <OperatorValueSelect {...props(PropertyType.Numeric)} />
        </>
    )
}

export function OperatorValueWithBooleanProperty(): JSX.Element {
    return (
        <>
            <h1>Boolean Property</h1>
            <OperatorValueSelect {...props(PropertyType.Boolean)} />
        </>
    )
}

export function OperatorValueWithSelectorProperty(): JSX.Element {
    return (
        <>
            <h1>CSS Selector Property</h1>
            <OperatorValueSelect {...props(PropertyType.Selector)} />
        </>
    )
}

export function OperatorValueWithUnknownProperty(): JSX.Element {
    return (
        <>
            <h1>Property without specific type</h1>
            <OperatorValueSelect {...props()} />
        </>
    )
}
