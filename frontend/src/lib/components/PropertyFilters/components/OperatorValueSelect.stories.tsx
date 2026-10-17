import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import {
    OperatorValueSelect,
    OperatorValueSelectProps,
} from 'lib/components/PropertyFilters/components/OperatorValueSelect'

import { PropertyDefinition, PropertyFilterType, PropertyOperator, PropertyType } from '~/types'

import { expect, userEvent, waitFor, within } from 'storybook/test'

const meta: Meta<OperatorValueSelectProps> = {
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

const longRegex =
    '^https://example\\.com/(products|pricing|documentation|integrations|customer-stories|case-studies|features|solutions|guides|tutorials|reference|changelog|support)/[a-z0-9-]+$'

function LongRegexValue(): JSX.Element {
    const [value, setValue] = useState(longRegex)

    return (
        <div className="w-96 max-w-full">
            <OperatorValueSelect
                type={PropertyFilterType.Event}
                propertyKey="$current_url"
                operator={PropertyOperator.Regex}
                value={value}
                onChange={(_, nextValue) => setValue(String(nextValue))}
                propertyDefinitions={[makePropertyDefinition('$current_url', PropertyType.String)]}
                editable
            />
        </div>
    )
}

export const LongRegexValueCanBeEdited: StoryObj<OperatorValueSelectProps> = {
    render: () => <LongRegexValue />,
    parameters: { testOptions: { viewport: { width: 650, height: 850 } } },
    play: async ({ canvasElement }) => {
        const input = within(canvasElement).getByRole('textbox')
        await userEvent.click(input)
        const editButton = await waitFor(() => {
            const button = document.querySelector<HTMLButtonElement>(
                '.Popover .LemonButtonWithSideAction__side-button button'
            )
            expect(button).toBeInTheDocument()
            expect(button!.getBoundingClientRect().right).toBeLessThanOrEqual(window.innerWidth - 8)
            return button!
        })
        await userEvent.click(editButton)
        await waitFor(() => expect(input).toHaveValue(longRegex))
    },
}
