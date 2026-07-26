import { createEvent, fireEvent, render } from '@testing-library/react'

import { LemonInput } from './LemonInput'

describe('LemonInput', () => {
    it('does not call Enter handlers while composing with an IME', () => {
        const onKeyDown = jest.fn()
        const onPressEnter = jest.fn()
        const { container } = render(<LemonInput onKeyDown={onKeyDown} onPressEnter={onPressEnter} />)
        const input = container.querySelector('input')!
        const event = createEvent.keyDown(input, { key: 'Enter' })
        Object.defineProperty(event, 'isComposing', { value: true })

        fireEvent(input, event)

        expect(onKeyDown).not.toHaveBeenCalled()
        expect(onPressEnter).not.toHaveBeenCalled()
    })

    it('calls Enter handlers after composition ends', () => {
        const onKeyDown = jest.fn()
        const onPressEnter = jest.fn()
        const { container } = render(<LemonInput onKeyDown={onKeyDown} onPressEnter={onPressEnter} />)

        fireEvent.keyDown(container.querySelector('input')!, { key: 'Enter' })

        expect(onPressEnter).toHaveBeenCalledTimes(1)
        expect(onKeyDown).toHaveBeenCalledTimes(1)
    })

    it('forwards non-Enter key handlers', () => {
        const onKeyDown = jest.fn()
        const onPressEnter = jest.fn()
        const { container } = render(<LemonInput onKeyDown={onKeyDown} onPressEnter={onPressEnter} />)

        fireEvent.keyDown(container.querySelector('input')!, { key: 'a' })

        expect(onKeyDown).toHaveBeenCalledTimes(1)
        expect(onPressEnter).not.toHaveBeenCalled()
    })

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
