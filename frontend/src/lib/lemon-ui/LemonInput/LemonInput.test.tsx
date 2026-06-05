import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { LemonInput } from './LemonInput'

describe('LemonInput', () => {
    afterEach(() => {
        cleanup()
    })

    describe('IME composition Enter guard', () => {
        it('does not call onPressEnter when Enter is pressed during IME composition', () => {
            const onPressEnter = jest.fn()
            render(<LemonInput onPressEnter={onPressEnter} value="" />)
            const input = screen.getByRole('textbox')

            fireEvent.keyDown(input, { key: 'Enter', isComposing: true })

            expect(onPressEnter).not.toHaveBeenCalled()
        })

        it('calls onPressEnter when Enter is pressed outside of IME composition', () => {
            const onPressEnter = jest.fn()
            render(<LemonInput onPressEnter={onPressEnter} value="" />)
            const input = screen.getByRole('textbox')

            fireEvent.keyDown(input, { key: 'Enter', isComposing: false })

            expect(onPressEnter).toHaveBeenCalledTimes(1)
        })

        it('does not call consumer onKeyDown for Enter pressed during IME composition', () => {
            const onKeyDown = jest.fn()
            render(<LemonInput onKeyDown={onKeyDown} value="" />)
            const input = screen.getByRole('textbox')

            fireEvent.keyDown(input, { key: 'Enter', isComposing: true })

            expect(onKeyDown).not.toHaveBeenCalled()
        })

        it('forwards consumer onKeyDown for Enter outside of IME composition', () => {
            const onKeyDown = jest.fn()
            render(<LemonInput onKeyDown={onKeyDown} value="" />)
            const input = screen.getByRole('textbox')

            fireEvent.keyDown(input, { key: 'Enter', isComposing: false })

            expect(onKeyDown).toHaveBeenCalledTimes(1)
        })

        it('forwards consumer onKeyDown for non-Enter keys even during composition', () => {
            const onKeyDown = jest.fn()
            render(<LemonInput onKeyDown={onKeyDown} value="" />)
            const input = screen.getByRole('textbox')

            fireEvent.keyDown(input, { key: 'a', isComposing: true })

            expect(onKeyDown).toHaveBeenCalledTimes(1)
        })
    })
})
