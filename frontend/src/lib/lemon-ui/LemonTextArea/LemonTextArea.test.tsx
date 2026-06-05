import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { LemonTextArea } from './LemonTextArea'

describe('LemonTextArea', () => {
    afterEach(() => {
        cleanup()
    })

    describe('IME composition Enter guard', () => {
        it('does not call onPressEnter when Enter is pressed during IME composition', () => {
            const onPressEnter = jest.fn()
            render(<LemonTextArea onPressEnter={onPressEnter} value="" />)
            const textarea = screen.getByRole('textbox')

            fireEvent.keyDown(textarea, { key: 'Enter', isComposing: true })

            expect(onPressEnter).not.toHaveBeenCalled()
        })

        it('calls onPressEnter when Enter is pressed outside of IME composition', () => {
            const onPressEnter = jest.fn()
            render(<LemonTextArea onPressEnter={onPressEnter} value="hello" />)
            const textarea = screen.getByRole('textbox')

            fireEvent.keyDown(textarea, { key: 'Enter', isComposing: false })

            expect(onPressEnter).toHaveBeenCalledTimes(1)
            expect(onPressEnter).toHaveBeenCalledWith('hello')
        })

        it('does not call onPressCmdEnter when Cmd+Enter is pressed during IME composition', () => {
            const onPressCmdEnter = jest.fn()
            render(<LemonTextArea onPressCmdEnter={onPressCmdEnter} value="hi" />)
            const textarea = screen.getByRole('textbox')

            fireEvent.keyDown(textarea, { key: 'Enter', metaKey: true, isComposing: true })

            expect(onPressCmdEnter).not.toHaveBeenCalled()
        })

        it('does not call consumer onKeyDown for Enter pressed during IME composition', () => {
            const onKeyDown = jest.fn()
            render(<LemonTextArea onKeyDown={onKeyDown} onPressCmdEnter={jest.fn()} value="" />)
            const textarea = screen.getByRole('textbox')

            fireEvent.keyDown(textarea, { key: 'Enter', isComposing: true })

            expect(onKeyDown).not.toHaveBeenCalled()
        })

        it('forwards consumer onKeyDown for Enter outside of IME composition', () => {
            const onKeyDown = jest.fn()
            render(<LemonTextArea onKeyDown={onKeyDown} onPressCmdEnter={jest.fn()} value="" />)
            const textarea = screen.getByRole('textbox')

            fireEvent.keyDown(textarea, { key: 'Enter', isComposing: false })

            expect(onKeyDown).toHaveBeenCalledTimes(1)
        })

        it('forwards consumer onKeyDown for non-Enter keys even during composition', () => {
            const onKeyDown = jest.fn()
            render(<LemonTextArea onKeyDown={onKeyDown} onPressCmdEnter={jest.fn()} value="" />)
            const textarea = screen.getByRole('textbox')

            fireEvent.keyDown(textarea, { key: 'a', isComposing: true })

            expect(onKeyDown).toHaveBeenCalledTimes(1)
        })
    })
})
