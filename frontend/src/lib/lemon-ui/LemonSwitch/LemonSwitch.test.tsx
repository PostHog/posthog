import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { LemonSwitch } from './LemonSwitch'

describe('LemonSwitch', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        { checked: false as const, ariaChecked: 'false', nextChecked: true },
        { checked: true as const, ariaChecked: 'true', nextChecked: false },
        { checked: 'indeterminate' as const, ariaChecked: 'mixed', nextChecked: true },
    ])(
        'exposes aria-checked "$ariaChecked" and resolves a click to $nextChecked',
        ({ checked, ariaChecked, nextChecked }) => {
            const onChange = jest.fn()
            render(<LemonSwitch checked={checked} onChange={onChange} />)

            const button = screen.getByRole('switch')
            expect(button).toHaveAttribute('aria-checked', ariaChecked)
            fireEvent.click(button)
            expect(onChange).toHaveBeenCalledWith(nextChecked)
        }
    )

    it.each([
        { value: true, expected: 'true' },
        { value: false, expected: 'false' },
        { value: 'image', expected: 'image' },
    ])('forwards data-ph-capture-attribute-* ($value) onto the clickable element', ({ value, expected }) => {
        render(
            <LemonSwitch
                checked={false}
                onChange={() => {}}
                data-attr="my-switch"
                data-ph-capture-attribute-will-be-enabled={value}
            />
        )

        const button = screen.getByRole('switch')
        expect(button).toHaveAttribute('data-ph-capture-attribute-will-be-enabled', expected)
    })

    it('renders without capture attributes', () => {
        render(<LemonSwitch checked={true} onChange={() => {}} data-attr="my-switch" />)

        const button = screen.getByRole('switch')
        expect(button).toHaveAttribute('data-attr', 'my-switch')
        expect(button).not.toHaveAttribute('data-ph-capture-attribute-will-be-enabled')
    })
})
