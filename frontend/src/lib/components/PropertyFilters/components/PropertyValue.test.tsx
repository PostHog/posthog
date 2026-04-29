import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator, PropertyType } from '~/types'

import { PropertyValue } from './PropertyValue'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('PropertyValue', () => {
    let loadPropertyValuesSpy: jest.SpyInstance

    beforeEach(() => {
        useMocks({
            get: {
                '/api/event/values': {
                    results: [{ name: 'Chrome' }, { name: 'Firefox' }, { name: 'Safari' }],
                    refreshing: false,
                },
                '/api/environments/:team/events/values': {
                    results: [{ name: 'Chrome' }, { name: 'Firefox' }, { name: 'Safari' }],
                    refreshing: false,
                },
            },
        })
        initKeaTests()
        propertyDefinitionsModel.mount()
        loadPropertyValuesSpy = jest.spyOn(propertyDefinitionsModel.actions, 'loadPropertyValues')
    })

    afterEach(() => {
        cleanup()
    })

    it('does not re-fetch property values when selecting a value from the dropdown', async () => {
        const onSet = jest.fn()
        render(
            <Provider>
                <PropertyValue
                    propertyKey="$browser"
                    type={PropertyFilterType.Event}
                    operator={PropertyOperator.Exact}
                    onSet={onSet}
                    value={[]}
                />
            </Provider>
        )

        // Focus the input to open the dropdown
        const input = screen.getByRole('textbox')
        userEvent.click(input)

        // Wait for options to load and appear (300ms debounce + async fetch needs headroom under CI load)
        await waitFor(
            () => {
                expect(screen.getByText('Chrome')).toBeInTheDocument()
            },
            { timeout: 3000 }
        )

        const callCountAfterLoad = loadPropertyValuesSpy.mock.calls.length

        // Select a value from the dropdown
        userEvent.click(screen.getByText('Chrome'))
        // Flush pending microtasks so any async loadPropertyValues calls settle before we assert
        await new Promise((r) => setTimeout(r, 0))

        // loadPropertyValues should not have been called again
        expect(loadPropertyValuesSpy.mock.calls.length).toBe(callCountAfterLoad)
    })

    it('renders with showInlineValidationErrors prop', () => {
        const onSet = jest.fn()
        render(
            <Provider>
                <PropertyValue
                    propertyKey="test_prop"
                    type={PropertyFilterType.Event}
                    operator={PropertyOperator.Exact}
                    onSet={onSet}
                    value={[]}
                    validationError="Test validation error"
                    showInlineValidationErrors
                />
            </Provider>
        )

        // Check that the error message is displayed when showInlineValidationErrors is true
        expect(screen.getByText('Test validation error')).toBeInTheDocument()
    })

    it('displays validation error messages', async () => {
        const onSet = jest.fn()
        render(
            <Provider>
                <PropertyValue
                    propertyKey="test"
                    type={PropertyFilterType.Event}
                    operator={PropertyOperator.Exact}
                    onSet={onSet}
                    value={[]}
                    validationError="This is a test error"
                    showInlineValidationErrors
                />
            </Provider>
        )

        // Check that the error message is displayed
        expect(screen.getByText('This is a test error')).toBeInTheDocument()

        // Check that the error container has the danger class
        const errorContainer = screen.getByText('This is a test error').closest('div')
        expect(errorContainer).toHaveClass('text-danger')
    })

    it('allows regex input for numeric properties', async () => {
        propertyDefinitionsModel.actions.updatePropertyDefinitions({
            'event/userId': {
                id: 'userId',
                name: 'userId',
                property_type: PropertyType.Numeric,
                is_numerical: true,
                is_seen_on_filtered_events: false,
            },
        })

        const onSet = jest.fn()
        render(
            <Provider>
                <PropertyValue
                    propertyKey="userId"
                    type={PropertyFilterType.Event}
                    operator={PropertyOperator.Regex}
                    onSet={onSet}
                    value={[]}
                />
            </Provider>
        )

        const input = screen.getByRole('textbox')
        await userEvent.type(input, 'user.*7$')

        expect(input).toHaveValue('user.*7$')
    })

    it('keeps numeric-only input for non-regex numeric properties', async () => {
        propertyDefinitionsModel.actions.updatePropertyDefinitions({
            'event/userId': {
                id: 'userId',
                name: 'userId',
                property_type: PropertyType.Numeric,
                is_numerical: true,
                is_seen_on_filtered_events: false,
            },
        })

        const onSet = jest.fn()
        render(
            <Provider>
                <PropertyValue
                    propertyKey="userId"
                    type={PropertyFilterType.Event}
                    operator={PropertyOperator.Exact}
                    onSet={onSet}
                    value={[]}
                />
            </Provider>
        )

        const input = screen.getByRole('textbox')
        await userEvent.type(input, '7a.8$')

        expect(input).toHaveValue('7.8')
    })
})
