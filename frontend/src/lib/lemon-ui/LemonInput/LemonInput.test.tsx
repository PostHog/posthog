import { fireEvent, render } from '@testing-library/react'

import { LemonInput } from './LemonInput'

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
})
