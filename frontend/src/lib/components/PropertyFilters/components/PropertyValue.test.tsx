import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { PropertyValue } from './PropertyValue'
import { PropertyFilterType, PropertyOperator } from '~/types'
import { initKeaTests } from '~/test/init'

// Mock kea hooks
jest.mock('kea', () => {
    const actual = jest.requireActual('kea')
    return {
        ...actual,
        useValues: jest.fn(() => ({
            formatPropertyValueForDisplay: (_key: string, value: any) => value,
            describeProperty: () => null,
            options: {
                testProp: {
                    values: [{ name: true }, { name: false }, { name: 'some-variant' }, { name: 'true' }],
                    status: 'loaded',
                    allowCustomValues: true,
                },
            },
        })),
        useActions: jest.fn(() => ({
            loadPropertyValues: jest.fn(),
        })),
    }
})

describe('PropertyValue with Flag Dependencies', () => {
    beforeEach(() => {
        initKeaTests()
    })

    const defaultProps = {
        propertyKey: 'testProp',
        type: PropertyFilterType.FlagDependency,
        operator: PropertyOperator.Exact,
        value: [true, false, 'some-variant'],
        onSet: jest.fn(),
        endpoint: 'test',
        eventNames: [],
        addRelativeDateTimeOptions: false,
        groupTypeIndex: undefined,
        editable: true,
        preloadValues: false,
    }

    it('preserves boolean values for flag dependencies', () => {
        render(
            <Provider>
                <PropertyValue {...defaultProps} />
            </Provider>
        )

        // Debug what's actually rendered

        // The component should render the boolean values
        // Since it's a select component, the values should be in the placeholder or input
        const input = screen.getByPlaceholderText('true')
        expect(input).toBeInTheDocument()
    })

    it('handles mixed boolean and string values', () => {
        const props = {
            ...defaultProps,
            value: [true, 'true', false, 'some-variant'],
        }

        render(
            <Provider>
                <PropertyValue {...props} />
            </Provider>
        )

        // Should display all values properly
        expect(screen.getByText('true')).toBeInTheDocument()
        expect(screen.getByText('false')).toBeInTheDocument()
        expect(screen.getByText('some-variant')).toBeInTheDocument()
    })
})
