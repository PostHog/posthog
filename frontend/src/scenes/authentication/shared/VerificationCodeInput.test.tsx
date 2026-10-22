import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'

import { VerificationCodeInput } from './VerificationCodeInput'

describe('VerificationCodeInput', () => {
    afterEach(() => {
        cleanup()
    })

    function renderInput(value = ''): {
        input: HTMLInputElement
        onChange: jest.Mock
        onComplete: jest.Mock
    } {
        const onChange = jest.fn()
        const onComplete = jest.fn()
        const { container } = render(
            <VerificationCodeInput value={value} onChange={onChange} onComplete={onComplete} />
        )
        // Separate inputs per digit make a mobile keyboard close each time focus moves to the next slot
        const inputs = container.querySelectorAll('input')
        expect(inputs).toHaveLength(1)
        expect(inputs[0]).toHaveAttribute('autocomplete', 'one-time-code')
        expect(inputs[0]).toHaveAttribute('inputmode', 'numeric')
        return { input: inputs[0], onChange, onComplete }
    }

    it.each([
        ['autofill', '123456'],
        ['autofill with noise', ' 123-456​'],
    ])('completes the code on %s', (_label, raw) => {
        const { input, onChange, onComplete } = renderInput()

        fireEvent.change(input, { target: { value: raw } })

        expect(onChange).toHaveBeenCalledWith('123456')
        expect(onComplete).toHaveBeenCalledWith('123456')
    })

    it('does not complete a partial code', () => {
        const { input, onChange, onComplete } = renderInput('12345')

        fireEvent.change(input, { target: { value: '1234' } })

        expect(onChange).toHaveBeenCalledWith('1234')
        expect(onComplete).not.toHaveBeenCalled()
    })

    it('replaces the whole code on a paste of a full code, even when the field is full', () => {
        const { input, onChange, onComplete } = renderInput('111111')

        fireEvent.paste(input, { clipboardData: { getData: () => '123 456' } })

        expect(onChange).toHaveBeenCalledWith('123456')
        expect(onComplete).toHaveBeenCalledWith('123456')
    })
})
