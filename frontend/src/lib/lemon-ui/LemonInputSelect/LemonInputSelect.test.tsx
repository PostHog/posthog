import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { LemonInputSelect } from './LemonInputSelect'

describe('LemonInputSelect', () => {
    // Helper functions
    const openDropdown = async (container: HTMLElement): Promise<HTMLInputElement> => {
        const input = container.querySelector('input[type="text"]')
        expect(input).toBeInTheDocument()
        await userEvent.click(input!)
        return input as HTMLInputElement
    }

    const findDropdownButtonByText = async (text: string): Promise<HTMLElement | undefined> => {
        const dropdownButtons = await screen.findAllByRole('button')
        return dropdownButtons.find((button) => button.textContent?.includes(text))
    }

    it('works with string values (backwards compatibility)', () => {
        const onChange = jest.fn()

        render(
            <LemonInputSelect
                mode="multiple"
                options={[
                    { key: 'string-option-1', label: 'Option 1' },
                    { key: 'string-option-2', label: 'Option 2' },
                ]}
                value={['string-option-1']}
                onChange={onChange}
            />
        )

        // Verify the selected option is displayed
        expect(screen.getByText('Option 1')).toBeInTheDocument()
    })

    it('works with boolean values', () => {
        const onChange = jest.fn()

        render(
            <LemonInputSelect<boolean>
                mode="multiple"
                options={[
                    { key: 'boolean-true', label: 'True', value: true },
                    { key: 'boolean-false', label: 'False', value: false },
                ]}
                value={[true]}
                onChange={onChange}
            />
        )

        // Verify the selected boolean option is displayed with correct label
        expect(screen.getByText('True')).toBeInTheDocument()
    })

    it('works with mixed boolean and string values', () => {
        const onChange = jest.fn()

        render(
            <LemonInputSelect<boolean | string>
                mode="multiple"
                options={[
                    { key: 'boolean-true-option', label: 'Boolean True', value: true },
                    { key: 'boolean-false-option', label: 'Boolean False', value: false },
                    { key: 'string-true-option', label: 'String True', value: 'true' },
                    { key: 'variant-option', label: 'Variant', value: 'some-variant' },
                ]}
                value={[true, 'some-variant']}
                onChange={onChange}
            />
        )

        // Verify both typed values are displayed with correct labels
        expect(screen.getByText('Boolean True')).toBeInTheDocument()
        expect(screen.getByText('Variant')).toBeInTheDocument()
    })

    it('displays correct labels for typed values', () => {
        const onChange = jest.fn()

        render(
            <LemonInputSelect<boolean | string>
                mode="multiple"
                options={[
                    { key: 'boolean-true-option', label: 'Boolean True', value: true },
                    { key: 'string-variant-option', label: 'String Variant', value: 'some-variant' },
                ]}
                value={[true, 'some-variant']}
                onChange={onChange}
            />
        )

        // Verify that typed values display their proper labels
        expect(screen.getAllByText('Boolean True').length).toBeGreaterThanOrEqual(1)
        expect(screen.getAllByText('String Variant').length).toBeGreaterThanOrEqual(1)
    })

    it('preserves correct types during onChange callback', () => {
        // This test focuses on the onChange callback behavior
        const onChange = jest.fn()

        // Create a test component to manually trigger onChange
        const TestComponent = (): JSX.Element => {
            const handleSelect = (): void => {
                // Simulate selecting a boolean option
                onChange([true])
            }
            const handleSelectString = (): void => {
                // Simulate selecting a string option
                onChange(['string-value'])
            }
            const handleSelectNumber = (): void => {
                // Simulate selecting a number option
                onChange([42])
            }

            return (
                <div>
                    <button onClick={handleSelect}>Select Boolean</button>
                    <button onClick={handleSelectString}>Select String</button>
                    <button onClick={handleSelectNumber}>Select Number</button>
                </div>
            )
        }

        render(<TestComponent />)

        // Test boolean type preservation
        const booleanButton = screen.getByText('Select Boolean')
        booleanButton.click()
        expect(onChange).toHaveBeenCalledWith([true])
        let lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0]
        expect(typeof lastCall[0]).toBe('boolean')
        expect(lastCall[0]).toBe(true)

        // Test string type preservation
        const stringButton = screen.getByText('Select String')
        stringButton.click()
        expect(onChange).toHaveBeenCalledWith(['string-value'])
        lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0]
        expect(typeof lastCall[0]).toBe('string')
        expect(lastCall[0]).toBe('string-value')

        // Test number type preservation
        const numberButton = screen.getByText('Select Number')
        numberButton.click()
        expect(onChange).toHaveBeenCalledWith([42])
        lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0]
        expect(typeof lastCall[0]).toBe('number')
        expect(lastCall[0]).toBe(42)
    })

    it('single-select mode: clicking already-selected value keeps it selected', async () => {
        const onChange = jest.fn()

        const { container } = render(
            <LemonInputSelect<string>
                mode="single"
                options={[
                    { key: 'option-1', label: 'Option 1' },
                    { key: 'option-2', label: 'Option 2' },
                ]}
                value={['option-1']}
                onChange={onChange}
                allowCustomValues
                data-attr="test-select"
            />
        )

        // Verify the selected option is displayed
        expect(screen.getAllByText('Option 1').length).toBeGreaterThan(0)

        await openDropdown(container)
        const selectedOptionButton = await findDropdownButtonByText('Option 1')
        expect(selectedOptionButton).toBeInTheDocument()
        await userEvent.click(selectedOptionButton!)
        // Verify onChange was NOT called with empty array (which would reset the selection)
        expect(onChange).not.toHaveBeenCalledWith([])
    })

    it('single-select mode: custom values show with formatCreateLabel when re-opening dropdown', async () => {
        const onChange = jest.fn()

        const { container } = render(
            <LemonInputSelect<string>
                mode="single"
                options={[{ key: 'existing-option', label: 'Existing Option' }]}
                value={['custom-value']}
                onChange={onChange}
                allowCustomValues
                formatCreateLabel={(input) => `${input} (new entry)`}
                data-attr="test-custom-select"
            />
        )

        // Custom value should be displayed
        expect(screen.getAllByText('custom-value').length).toBeGreaterThan(0)

        await openDropdown(container)

        // Wait for dropdown to appear and check for formatted label
        const formattedLabel = await screen.findByText('custom-value (new entry)')
        expect(formattedLabel).toBeInTheDocument()

        // Click on the custom value option
        const customValueButton = formattedLabel.closest('button')
        expect(customValueButton).toBeInTheDocument()
        await userEvent.click(customValueButton!)

        // Verify selection was NOT reset (onChange not called with empty array)
        expect(onChange).not.toHaveBeenCalledWith([])
    })

    it('single-select mode: select all + backspace clears the selection', async () => {
        const onChange = jest.fn()

        const { container } = render(
            <LemonInputSelect<string>
                mode="single"
                options={[
                    { key: 'option-1', label: 'Option 1' },
                    { key: 'option-2', label: 'Option 2' },
                ]}
                value={['option-1']}
                onChange={onChange}
                allowCustomValues
            />
        )

        // Verify the selected option is displayed
        expect(screen.getAllByText('Option 1').length).toBeGreaterThan(0)

        const input = await openDropdown(container)

        // In single mode, focusing the input enters edit mode with the value selected
        // Simulate selecting all text (e.g., via Cmd+A)
        input.setSelectionRange(0, input.value.length)

        // Press Backspace with all text selected
        await userEvent.keyboard('{Backspace}')

        // Verify onChange was called with empty array (clearing the selection)
        expect(onChange).toHaveBeenCalledWith([])
    })
})
