import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'

import { Provider } from 'kea'
import { TaxonomicPropertyFilter } from './TaxonomicPropertyFilter'
import { PropertyFilterType, PropertyOperator } from '~/types'
import { initKeaTests } from '~/test/init'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

// Mock dependencies to avoid issues with frimousse
jest.mock('lib/lemon-ui/LemonTextArea/LemonTextAreaMarkdown', () => ({
    LemonTextAreaMarkdown: () => null,
}))

jest.mock('lib/components/EmojiPicker/EmojiPickerPopover', () => ({
    EmojiPickerPopover: () => null,
}))

// Mock the OperatorValueSelect component to capture onChange calls
jest.mock('./OperatorValueSelect', () => ({
    OperatorValueSelect: ({ onChange, ...props }: any) => {
        // Store the onChange handler so we can call it in tests
        window.mockOperatorValueSelectOnChange = onChange
        return (
            <div data-testid="operator-value-select">
                <input
                    data-testid="value-input"
                    value={props.value || ''}
                    onChange={(e) => onChange(props.operator, e.target.value)}
                />
            </div>
        )
    },
}))

declare global {
    interface Window {
        mockOperatorValueSelectOnChange: any
    }
}

describe('TaxonomicPropertyFilter', () => {
    beforeEach(() => {
        initKeaTests()
        window.mockOperatorValueSelectOnChange = undefined
    })

    const defaultProps = {
        index: 0,
        filters: [],
        setFilter: jest.fn(),
        taxonomicGroupTypes: [
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.FeatureFlags,
        ],
        editable: true,
        eventNames: [],
        propertyDefinitions: {},
        onComplete: jest.fn(),
        disablePopover: false,
    }

    describe('value handling in onChange', () => {
        const testCases = [
            { value: false, description: 'preserves boolean false' },
            { value: 0, description: 'preserves zero' },
            { value: '', description: 'preserves empty string' },
            { value: null, description: 'preserves null' },
            { value: 'test', description: 'preserves string values' },
            { value: 123, description: 'preserves numeric values' },
            { value: true, description: 'preserves boolean true' },
        ]

        testCases.forEach(({ value, description }) => {
            it(description, async () => {
                const setFilterMock = jest.fn()
                const filter = {
                    key: 'test_property',
                    type: PropertyFilterType.Event as PropertyFilterType.Event,
                    operator: PropertyOperator.Exact,
                    value: 'initial',
                }

                render(
                    <Provider>
                        <TaxonomicPropertyFilter {...defaultProps} filters={[filter]} setFilter={setFilterMock} />
                    </Provider>
                )

                // Simulate the OperatorValueSelect onChange being called
                if (window.mockOperatorValueSelectOnChange) {
                    window.mockOperatorValueSelectOnChange(PropertyOperator.Exact, value)
                }

                // Verify setFilter was called with the correct value
                expect(setFilterMock).toHaveBeenCalledWith(0, {
                    key: 'test_property',
                    value: value, // Should preserve the exact value, not convert to null
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                    label: undefined,
                })
            })
        })

        it('converts undefined to null', async () => {
            const setFilterMock = jest.fn()
            const filter = {
                key: 'test_property',
                type: PropertyFilterType.Event as PropertyFilterType.Event,
                operator: PropertyOperator.Exact,
                value: 'initial',
            }

            render(
                <Provider>
                    <TaxonomicPropertyFilter {...defaultProps} filters={[filter]} setFilter={setFilterMock} />
                </Provider>
            )

            // Simulate the OperatorValueSelect onChange being called with undefined
            if (window.mockOperatorValueSelectOnChange) {
                window.mockOperatorValueSelectOnChange(PropertyOperator.Exact, undefined)
            }

            // Verify setFilter was called with null instead of undefined
            expect(setFilterMock).toHaveBeenCalledWith(0, {
                key: 'test_property',
                value: null, // undefined should be converted to null
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
                label: undefined,
            })
        })
    })

    describe('feature flag dependency handling', () => {
        it('preserves boolean values for flag dependencies', async () => {
            const setFilterMock = jest.fn()
            const filter = {
                key: 'test_flag',
                type: PropertyFilterType.FlagDependency as PropertyFilterType.FlagDependency,
                operator: PropertyOperator.Exact,
                value: true,
                label: 'Test Flag',
            }

            render(
                <Provider>
                    <TaxonomicPropertyFilter {...defaultProps} filters={[filter]} setFilter={setFilterMock} />
                </Provider>
            )

            // Verify the component renders the flag dependency label
            expect(screen.getByText('Test Flag')).toBeInTheDocument()

            // Simulate changing to false
            if (window.mockOperatorValueSelectOnChange) {
                window.mockOperatorValueSelectOnChange(PropertyOperator.Exact, false)
            }

            // Verify setFilter preserves false value
            expect(setFilterMock).toHaveBeenCalledWith(
                0,
                expect.objectContaining({
                    value: false, // Should be false, not null
                    type: PropertyFilterType.FlagDependency as PropertyFilterType.FlagDependency,
                })
            )
        })

        it('handles mixed boolean and variant values', () => {
            const setFilterMock = jest.fn()
            const filter = {
                key: 'test_flag',
                type: PropertyFilterType.FlagDependency as PropertyFilterType.FlagDependency,
                operator: PropertyOperator.Exact,
                value: [true, false, 'some-variant'],
                label: 'Test Flag',
            }

            render(
                <Provider>
                    <TaxonomicPropertyFilter {...defaultProps} filters={[filter]} setFilter={setFilterMock} />
                </Provider>
            )

            // Verify setFilter was called with the correct values
            if (window.mockOperatorValueSelectOnChange) {
                window.mockOperatorValueSelectOnChange(PropertyOperator.Exact, [false, 'some-variant', true])
            }

            // Verify setFilter was called with mixed values preserved
            expect(setFilterMock).toHaveBeenCalledWith(
                0,
                expect.objectContaining({
                    value: [false, 'some-variant', true],
                    type: PropertyFilterType.FlagDependency as PropertyFilterType.FlagDependency,
                })
            )

            // Test value changes preserve types
            if (window.mockOperatorValueSelectOnChange) {
                window.mockOperatorValueSelectOnChange(PropertyOperator.Exact, [false, 'some-variant', true])
            }

            expect(setFilterMock).toHaveBeenCalledWith(
                0,
                expect.objectContaining({
                    value: [false, 'some-variant', true],
                    type: PropertyFilterType.FlagDependency as PropertyFilterType.FlagDependency,
                })
            )
        })
    })
})
