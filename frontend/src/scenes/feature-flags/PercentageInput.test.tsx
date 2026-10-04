import { fireEvent, render } from '@testing-library/react'
import { useState } from 'react'

import { PercentageInput } from './PercentageInput'

function ControlledPercentageInput({ onValue }: { onValue: (value: number) => void }): JSX.Element {
    const [value, setValue] = useState(50)
    return (
        <PercentageInput
            value={value}
            onChange={(next) => {
                setValue(next)
                onValue(next)
            }}
        />
    )
}

describe('PercentageInput', () => {
    it.each([
        ['a value above the maximum', '150', '100', 100],
        ['more precision than the input keeps', '1.234', '1.23', 1.23],
        ['a decimal tie', '1.005', '1.01', 1.01],
    ])('shows the stored value after clamping %s', (_name, typed, displayed, stored) => {
        const onValue = jest.fn()
        const { container } = render(<ControlledPercentageInput onValue={onValue} />)
        const input = container.querySelector('input') as HTMLInputElement

        fireEvent.focus(input)
        fireEvent.change(input, { target: { value: typed } })

        expect(input.value).toBe(displayed)
        expect(onValue).toHaveBeenLastCalledWith(stored)
    })

    it('stores zero when the field is cleared', () => {
        const onValue = jest.fn()
        const { container } = render(<ControlledPercentageInput onValue={onValue} />)
        const input = container.querySelector('input') as HTMLInputElement

        fireEvent.focus(input)
        fireEvent.change(input, { target: { value: '' } })

        expect(input.value).toBe('')
        expect(onValue).toHaveBeenLastCalledWith(0)
    })

    it('keeps a partial decimal entry typeable', () => {
        const onValue = jest.fn()
        const { container } = render(<ControlledPercentageInput onValue={onValue} />)
        const input = container.querySelector('input') as HTMLInputElement

        fireEvent.focus(input)
        fireEvent.change(input, { target: { value: '0.' } })
        fireEvent.change(input, { target: { value: '0.5' } })

        expect(input.value).toBe('0.5')
        expect(onValue).toHaveBeenLastCalledWith(0.5)
    })
})
