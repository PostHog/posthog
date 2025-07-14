import { render, screen } from '@testing-library/react'
import { PropertyValue } from './PropertyValue'
import { PropertyFilterType, PropertyOperator } from '~/types'

// Mock the dependencies
jest.mock('~/models/propertyDefinitionsModel', () => ({
    useValues: () => ({
        formatPropertyValueForDisplay: (_key: string, value: any) => value,
        describeProperty: () => null,
        options: {
            testProp: {
                values: [{ name: true }, { name: false }, { name: 'some-variant' }, { name: 'true' }],
                status: 'loaded',
                allowCustomValues: true,
            },
        },
    }),
    useActions: () => ({
        loadPropertyValues: jest.fn(),
    }),
}))

describe('PropertyValue with Flag Dependencies', () => {
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
        render(<PropertyValue {...defaultProps} />)

        // The component should render the boolean values
        expect(screen.getByText('true')).toBeInTheDocument()
        expect(screen.getByText('false')).toBeInTheDocument()
        expect(screen.getByText('some-variant')).toBeInTheDocument()
    })

    it('handles mixed boolean and string values', () => {
        const props = {
            ...defaultProps,
            value: [true, 'true', false, 'some-variant'],
        }

        render(<PropertyValue {...props} />)

        // Should display all values properly
        expect(screen.getByText('true')).toBeInTheDocument()
        expect(screen.getByText('false')).toBeInTheDocument()
        expect(screen.getByText('some-variant')).toBeInTheDocument()
    })
})
