import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'
import { LemonInputSelect } from './LemonInputSelect'

describe('LemonInputSelect', () => {
    it('works with string values (backwards compatibility)', () => {
        const onChange = jest.fn()

        render(
            <LemonInputSelect
                mode="multiple"
                options={[
                    { key: 'option1', label: 'Option 1' },
                    { key: 'option2', label: 'Option 2' },
                ]}
                value={['option1']}
                onChange={onChange}
            />
        )

        expect(screen.getByText('Option 1')).toBeInTheDocument()
    })

    it('works with boolean values', () => {
        const onChange = jest.fn()

        render(
            <LemonInputSelect<boolean>
                mode="multiple"
                options={[
                    { key: 'true', label: 'True', value: true },
                    { key: 'false', label: 'False', value: false },
                ]}
                value={[true]}
                onChange={onChange}
            />
        )

        expect(screen.getByText('True')).toBeInTheDocument()
    })

    it('works with mixed boolean and string values', () => {
        const onChange = jest.fn()

        render(
            <LemonInputSelect<boolean | string>
                mode="multiple"
                options={[
                    { key: 'boolean-true', label: 'Boolean True', value: true },
                    { key: 'boolean-false', label: 'Boolean False', value: false },
                    { key: 'string-true', label: 'String True', value: 'true' },
                    { key: 'variant', label: 'Variant', value: 'some-variant' },
                ]}
                value={[true, 'some-variant']}
                onChange={onChange}
            />
        )

        expect(screen.getByText('Boolean True')).toBeInTheDocument()
        expect(screen.getByText('Variant')).toBeInTheDocument()
    })

    it('displays correct labels for typed values', () => {
        const onChange = jest.fn()

        render(
            <LemonInputSelect<boolean | string>
                mode="multiple"
                options={[
                    { key: 'boolean-true', label: 'Boolean True', value: true },
                    { key: 'string-variant', label: 'String Variant', value: 'some-variant' },
                ]}
                value={[true, 'some-variant']}
                onChange={onChange}
            />
        )

        // Verify that typed values display their proper labels
        expect(screen.getAllByText('Boolean True').length).toBeGreaterThan(0)
        expect(screen.getAllByText('String Variant').length).toBeGreaterThan(0)
    })
})
