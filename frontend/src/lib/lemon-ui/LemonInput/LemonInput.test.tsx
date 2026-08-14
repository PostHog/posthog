import { fireEvent, render } from '@testing-library/react'
import { useState } from 'react'

import { LemonInput } from './LemonInput'

/** Mimics how consumers wire a number field: store what `onChange` gives us, optionally collapsing the
 * NaN of a cleared field back into a default, and optionally clamping. */
function NumberFieldHarness({
    fallback,
    clampMax,
    onValueChange,
}: {
    fallback?: number
    clampMax?: number
    onValueChange?: (value: number | undefined) => void
}): JSX.Element {
    const [value, setValue] = useState<number | undefined>(30)
    return (
        <LemonInput
            type="number"
            value={fallback !== undefined ? value || fallback : value}
            onChange={(newValue) => {
                const next = clampMax !== undefined && (newValue as number) > clampMax ? clampMax : newValue
                setValue(next)
                onValueChange?.(next)
            }}
        />
    )
}

/** Types `text` the way a keystroke does — appending to whatever the field already shows. */
function typeInto(input: HTMLInputElement, text: string): void {
    fireEvent.change(input, { target: { value: `${input.value}${text}` } })
}

describe('LemonInput', () => {
    it('does not refocus the native input when it handles the click itself', () => {
        const { container } = render(<LemonInput type="time" />)
        const wrapper = container.querySelector<HTMLElement>('.LemonInput')
        const input = container.querySelector<HTMLInputElement>('input')

        expect(wrapper).not.toBeNull()
        expect(input).not.toBeNull()

        const focus = jest.spyOn(input!, 'focus')

        fireEvent.click(input!)
        expect(focus).not.toHaveBeenCalled()

        fireEvent.click(wrapper!)
        expect(focus).toHaveBeenCalledTimes(1)
    })

    it.each([
        ['falls back to 0', 0],
        ['falls back to 100', 100],
        ['has no fallback', undefined],
    ])('keeps a cleared number field empty while typing, when the consumer %s', (_, fallback) => {
        const onValueChange = jest.fn()
        const { container } = render(<NumberFieldHarness fallback={fallback} onValueChange={onValueChange} />)
        const input = container.querySelector<HTMLInputElement>('input')!

        fireEvent.focus(input)
        fireEvent.change(input, { target: { value: '' } })
        expect(input.value).toBe('')

        // The next keystroke appends. Without the fix the field already holds the fallback, so this
        // lands as '05' or '1005' — and React leaves it there, because '05' and 5 compare equal.
        typeInto(input, '5')
        expect(input.value).toBe('5')
        expect(onValueChange).toHaveBeenLastCalledWith(5)
    })

    it('restores the consumer fallback once the cleared field loses focus', () => {
        const { container } = render(<NumberFieldHarness fallback={100} />)
        const input = container.querySelector<HTMLInputElement>('input')!

        fireEvent.focus(input)
        fireEvent.change(input, { target: { value: '' } })
        expect(input.value).toBe('')

        fireEvent.blur(input)
        expect(input.value).toBe('100')
    })

    it('still shows a value the consumer clamped while the field is focused', () => {
        // Pins the empty-only scope: covering the whole focused session instead would swallow clamping
        // and any programmatic update, such as a slider sharing the field's state.
        const { container } = render(<NumberFieldHarness clampMax={365} />)
        const input = container.querySelector<HTMLInputElement>('input')!

        fireEvent.focus(input)
        fireEvent.change(input, { target: { value: '9999' } })
        expect(input.value).toBe('365')
    })

    it.each([
        ['a bare zero', '0'],
        ['a decimal', '0.5'],
    ])('accepts %s entered into a cleared field', (_, entered) => {
        const onValueChange = jest.fn()
        const { container } = render(<NumberFieldHarness fallback={0} onValueChange={onValueChange} />)
        const input = container.querySelector<HTMLInputElement>('input')!

        fireEvent.focus(input)
        fireEvent.change(input, { target: { value: '' } })
        fireEvent.change(input, { target: { value: entered } })

        expect(input.value).toBe(entered)
        expect(onValueChange).toHaveBeenLastCalledWith(Number(entered))
    })

    it('leaves a half-typed number the browser cannot parse yet alone', () => {
        // A number input reports `value` as '' for an incomplete number like '-' or '0.', so the
        // consumer sees NaN and echoes its fallback. The field must keep showing what was typed.
        const { container } = render(<NumberFieldHarness fallback={0} />)
        const input = container.querySelector<HTMLInputElement>('input')!

        fireEvent.focus(input)
        fireEvent.change(input, { target: { value: '' } })
        fireEvent.change(input, { target: { value: '-' } })

        // jsdom applies value sanitization but keeps no record of the raw text, so '' is all we can
        // assert here — what matters is that React declined to write the fallback over it. A real
        // browser keeps the '-' visible on top of the same empty `value`.
        expect(input.value).toBe('')
    })

    it('leaves an uncontrolled number field uncontrolled while it is emptied', () => {
        // Consumers that pass only `defaultValue` have no echoed fallback to defend against, and
        // swapping their undefined value for '' would flip the input controlled and back again.
        const messages: string[] = []
        const consoleError = jest.spyOn(console, 'error').mockImplementation((...args) => {
            messages.push(args.map(String).join(' '))
        })
        try {
            const { container } = render(<LemonInput type="number" defaultValue={50} />)
            const input = container.querySelector<HTMLInputElement>('input')!

            fireEvent.focus(input)
            fireEvent.change(input, { target: { value: '' } })
            typeInto(input, '5')

            expect(messages.filter((message) => /uncontrolled input|controlled input/.test(message))).toEqual([])
        } finally {
            consoleError.mockRestore()
        }
    })

    it('drops the has-content style while a number field is drafting empty', () => {
        const { container } = render(<NumberFieldHarness fallback={100} />)
        const wrapper = container.querySelector<HTMLElement>('.LemonInput')!
        const input = container.querySelector<HTMLInputElement>('input')!

        expect(wrapper.classList).toContain('LemonInput--has-content')

        fireEvent.focus(input)
        fireEvent.change(input, { target: { value: '' } })
        // The consumer still holds 100 here — the class has to follow what is on screen, not the prop.
        expect(wrapper.classList).not.toContain('LemonInput--has-content')

        fireEvent.blur(input)
        expect(wrapper.classList).toContain('LemonInput--has-content')
    })

    it('ends the draft when Enter commits without blurring', () => {
        // A number input takes part in a form's implicit submission, and Enter fires no blur, so
        // without this the field keeps reading empty while the consumer's fallback is what just
        // got submitted. Deliberately not gated on an onPressEnter handler — implicit submission
        // happens whether or not the consumer wired one.
        const { container } = render(<NumberFieldHarness fallback={100} />)
        const input = container.querySelector<HTMLInputElement>('input')!

        fireEvent.focus(input)
        fireEvent.change(input, { target: { value: '' } })
        expect(input.value).toBe('')

        fireEvent.keyDown(input, { key: 'Enter' })
        expect(input.value).toBe('100')
    })

    it('leaves a cleared text input to its consumer', () => {
        function TextFieldHarness(): JSX.Element {
            const [value, setValue] = useState<string>('abc')
            return <LemonInput type="text" value={value || 'abc'} onChange={setValue} />
        }
        const { container } = render(<TextFieldHarness />)
        const input = container.querySelector<HTMLInputElement>('input')!

        fireEvent.focus(input)
        fireEvent.change(input, { target: { value: '' } })

        expect(input.value).toBe('abc')
    })
})
