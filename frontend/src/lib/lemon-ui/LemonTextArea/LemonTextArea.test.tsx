import { createEvent, fireEvent, render } from '@testing-library/react'

import { LemonTextArea } from './LemonTextArea'

describe('LemonTextArea', () => {
    it('does not call Enter or submit handlers while composing with an IME', () => {
        const onKeyDown = jest.fn()
        const onPressEnter = jest.fn()
        const onPressCmdEnter = jest.fn()
        const { container } = render(
            <>
                <LemonTextArea onKeyDown={onKeyDown} onPressEnter={onPressEnter} />
                <LemonTextArea onKeyDown={onKeyDown} onPressCmdEnter={onPressCmdEnter} />
            </>
        )
        const [enterTextArea, cmdEnterTextArea] = Array.from(container.querySelectorAll('textarea'))
        const enterEvent = createEvent.keyDown(enterTextArea, { key: 'Enter' })
        const cmdEnterEvent = createEvent.keyDown(cmdEnterTextArea, { key: 'Enter', ctrlKey: true })
        Object.defineProperty(enterEvent, 'isComposing', { value: true })
        Object.defineProperty(cmdEnterEvent, 'isComposing', { value: true })

        fireEvent(enterTextArea, enterEvent)
        fireEvent(cmdEnterTextArea, cmdEnterEvent)

        expect(onKeyDown).not.toHaveBeenCalled()
        expect(onPressEnter).not.toHaveBeenCalled()
        expect(onPressCmdEnter).not.toHaveBeenCalled()
    })

    it('calls Enter handlers after composition ends', () => {
        const onKeyDown = jest.fn()
        const onPressEnter = jest.fn()
        const { container } = render(<LemonTextArea onKeyDown={onKeyDown} onPressEnter={onPressEnter} value="Draft" />)

        fireEvent.keyDown(container.querySelector('textarea')!, { key: 'Enter' })

        expect(onPressEnter).toHaveBeenCalledWith('Draft')
        expect(onKeyDown).toHaveBeenCalledTimes(1)
    })

    it('calls Cmd/Ctrl + Enter handlers after composition ends', () => {
        const onKeyDown = jest.fn()
        const onPressCmdEnter = jest.fn()
        const { container } = render(
            <LemonTextArea onKeyDown={onKeyDown} onPressCmdEnter={onPressCmdEnter} value="Draft" />
        )

        fireEvent.keyDown(container.querySelector('textarea')!, { key: 'Enter', ctrlKey: true })

        expect(onPressCmdEnter).toHaveBeenCalledWith('Draft')
        expect(onKeyDown).toHaveBeenCalledTimes(1)
    })

    it('forwards non-Enter key handlers', () => {
        const onKeyDown = jest.fn()
        const onPressEnter = jest.fn()
        const { container } = render(<LemonTextArea onKeyDown={onKeyDown} onPressEnter={onPressEnter} />)

        fireEvent.keyDown(container.querySelector('textarea')!, { key: 'a' })

        expect(onKeyDown).toHaveBeenCalledTimes(1)
        expect(onPressEnter).not.toHaveBeenCalled()
    })
})
