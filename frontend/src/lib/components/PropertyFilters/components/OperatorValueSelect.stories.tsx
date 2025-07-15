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

const props = (type: PropertyType | undefined, editable: boolean): OperatorValueSelectProps => ({
    type: undefined,
    propertyKey: 'the_property',
    onChange: () => {},
    propertyDefinitions: [makePropertyDefinition('the_property', type)],
    defaultOpen: true,
    editable,
})

export function OperatorValueWithStringProperty(): JSX.Element {
    return (
        <>
            <h1>String Property</h1>
            <OperatorValueSelect {...props(PropertyType.String, true)} />
            <OperatorValueSelect {...props(PropertyType.String, false)} />
        </>
    )
}

export function OperatorValueWithDateTimeProperty(): JSX.Element {
    return (
        <>
            <h1>Date Time Property</h1>
            <OperatorValueSelect {...props(PropertyType.DateTime, true)} />
            <OperatorValueSelect {...props(PropertyType.DateTime, false)} />
        </>
    )
}

export function OperatorValueWithNumericProperty(): JSX.Element {
    return (
        <>
            <h1>Numeric Property</h1>
            <OperatorValueSelect {...props(PropertyType.Numeric, true)} />
            <OperatorValueSelect {...props(PropertyType.Numeric, false)} />
        </>
    )
}

export function OperatorValueWithBooleanProperty(): JSX.Element {
    return (
        <>
            <h1>Boolean Property</h1>
            <OperatorValueSelect {...props(PropertyType.Boolean, true)} />
            <OperatorValueSelect {...props(PropertyType.Boolean, false)} />
        </>
    )
}

export function OperatorValueWithSelectorProperty(): JSX.Element {
    return (
        <>
            <h1>CSS Selector Property</h1>
            <OperatorValueSelect {...props(PropertyType.Selector, true)} />
            <OperatorValueSelect {...props(PropertyType.Selector, false)} />
        </>
    )
}

export function OperatorValueWithUnknownProperty(): JSX.Element {
    return (
        <>
            <h1>Property without specific type</h1>
            <OperatorValueSelect {...props(undefined, true)} />
            <OperatorValueSelect {...props(undefined, false)} />
        </>
    )
}
