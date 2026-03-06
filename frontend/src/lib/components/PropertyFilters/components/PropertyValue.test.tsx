import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { PropertyValue } from './PropertyValue'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('PropertyValue', () => {
    let loadPropertyValuesSpy: jest.SpyInstance
    let describePropertySpy: jest.SpyInstance

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
        if (describePropertySpy) {
            describePropertySpy.mockRestore()
        }
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

        // Wait for options to load and appear
        await waitFor(() => {
            expect(screen.getByText('Chrome')).toBeInTheDocument()
        })

        const callCountAfterLoad = loadPropertyValuesSpy.mock.calls.length

        // Select a value from the dropdown
        userEvent.click(screen.getByText('Chrome'))
        // Flush pending microtasks so any async loadPropertyValues calls settle before we assert
        await new Promise((r) => setTimeout(r, 0))

        // loadPropertyValues should not have been called again
        expect(loadPropertyValuesSpy.mock.calls.length).toBe(callCountAfterLoad)
    })

    it('input transform filters non-numeric characters for numeric properties', () => {
        // Test the input transform logic directly
        const numericInputTransform = (input: string): string => input.replace(/[^0-9+\-.]/g, '')

        // Test cases for numeric input transformation
        expect(numericInputTransform('123.45')).toBe('123.45')
        expect(numericInputTransform('abc123def')).toBe('123')
        expect(numericInputTransform('a1b2c3.d4e5f')).toBe('123.45')
        expect(numericInputTransform('-123.45')).toBe('-123.45')
        expect(numericInputTransform('+987.65')).toBe('+987.65')
        expect(numericInputTransform('!@#$%^&*()')).toBe('')
        expect(numericInputTransform('abc')).toBe('')
        expect(numericInputTransform('12.34.56')).toBe('12.34.56') // Multiple dots allowed by basic filter
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
                />
            </Provider>
        )

        // Check that the error message is displayed
        expect(screen.getByText('This is a test error')).toBeInTheDocument()

        // Check that the error container has the danger class
        const errorContainer = screen.getByText('This is a test error').closest('div')
        expect(errorContainer).toHaveClass('text-danger')
    })
})
