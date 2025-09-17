import { Meta } from '@storybook/react'

import {
    OperatorValueSelect,
    OperatorValueSelectProps,
} from 'lib/components/PropertyFilters/components/OperatorValueSelect'

import { PropertyDefinition, PropertyOperator, PropertyType } from '~/types'

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

const props = (overrides: {
    type?: PropertyType | undefined
    editable?: boolean
    startVisible?: boolean
    operatorAllowlist?: PropertyOperator[]
}): OperatorValueSelectProps => ({
    type: undefined,
    propertyKey: 'the_property',
    onChange: () => {},
    propertyDefinitions: [makePropertyDefinition('the_property', overrides.type)],
    editable: overrides.editable ?? false,
    startVisible: overrides.startVisible,
    operatorAllowlist: overrides.operatorAllowlist,
})

export function OperatorValueWithStringProperty(): JSX.Element {
    return (
        <>
            <h1>String Property</h1>
            <OperatorValueSelect {...props({ type: PropertyType.String, editable: true })} />
            <OperatorValueSelect {...props({ type: PropertyType.String, editable: false })} />
        </>
    )
}

export function OperatorValueWithDateTimeProperty(): JSX.Element {
    return (
        <>
            <h1>Date Time Property</h1>
            <OperatorValueSelect {...props({ type: PropertyType.DateTime, editable: true })} />
            <OperatorValueSelect {...props({ type: PropertyType.DateTime, editable: false })} />
        </>
    )
}

export function OperatorValueWithNumericProperty(): JSX.Element {
    return (
        <>
            <h1>Numeric Property</h1>
            <OperatorValueSelect {...props({ type: PropertyType.Numeric, editable: true })} />
            <OperatorValueSelect {...props({ type: PropertyType.Numeric, editable: false })} />
        </>
    )
}

export function OperatorValueWithBooleanProperty(): JSX.Element {
    return (
        <>
            <h1>Boolean Property</h1>
            <OperatorValueSelect {...props({ type: PropertyType.Boolean, editable: true })} />
            <OperatorValueSelect {...props({ type: PropertyType.Boolean, editable: false })} />
        </>
    )
}

export function OperatorValueWithSelectorProperty(): JSX.Element {
    return (
        <>
            <h1>CSS Selector Property</h1>
            <OperatorValueSelect {...props({ type: PropertyType.Selector, editable: true })} />
            <OperatorValueSelect {...props({ type: PropertyType.Selector, editable: false })} />
        </>
    )
}

export function OperatorValueWithUnknownProperty(): JSX.Element {
    return (
        <>
            <h1>Property without specific type</h1>
            <OperatorValueSelect {...props({ editable: true })} />
            <OperatorValueSelect {...props({ editable: false })} />
        </>
    )
}

export function OperatorValueMenuOpen(): JSX.Element {
    return (
        <>
            <h1>Showing the options</h1>
            <OperatorValueSelect {...props({ editable: true, startVisible: true })} />
        </>
    )
}

export function OperatorValueMenuWithAllowlist(): JSX.Element {
    return (
        <>
            <h1>Limiting the options to just three</h1>
            <OperatorValueSelect
                {...props({
                    startVisible: true,
                    editable: true,
                    operatorAllowlist: [
                        PropertyOperator.IContains,
                        PropertyOperator.Exact,
                        PropertyOperator.NotIContains,
                    ],
                })}
            />
        </>
    )
}
