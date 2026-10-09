import '@testing-library/jest-dom'

import { act, cleanup, render } from '@testing-library/react'

import { LazyModalLoading } from './LazyModalLoading'

describe('LazyModalLoading', () => {
    beforeEach(() => jest.useFakeTimers())

    afterEach(() => {
        jest.useRealTimers()
        cleanup()
    })

    it('shows the loading modal only once the chunk is slow', () => {
        render(<LazyModalLoading isOpen onClose={jest.fn()} />)

        expect(document.querySelector('.Spinner')).not.toBeInTheDocument()

        act(() => {
            jest.advanceTimersByTime(200)
        })

        expect(document.querySelector('.Spinner')).toBeInTheDocument()
    })
})
