import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'

import { AuthenticatedShellFallback } from './AuthenticatedShellFallback'

describe('AuthenticatedShellFallback', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('takes spinner visibility from the app-level delay instead of restarting it', () => {
        const { container, rerender } = render(<AuthenticatedShellFallback showSpinner={false} />)

        act(() => {
            jest.advanceTimersByTime(2000)
        })
        expect(container.querySelector('.Spinner')).toBeNull()

        rerender(<AuthenticatedShellFallback showSpinner />)
        expect(container.querySelector('.Spinner')).not.toBeNull()
    })

    it('holds the reload prompt back until the shell load is clearly stuck', () => {
        render(<AuthenticatedShellFallback showSpinner />)

        expect(screen.queryByText('Reload')).not.toBeInTheDocument()

        act(() => {
            jest.advanceTimersByTime(8000)
        })

        expect(screen.getByText('Reload')).toBeInTheDocument()
    })

    it('reloads the page when the person clicks reload', () => {
        const reload = jest.fn()
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: { ...window.location, reload },
        })

        render(<AuthenticatedShellFallback showSpinner />)
        act(() => {
            jest.advanceTimersByTime(8000)
        })

        act(() => {
            screen.getByText('Reload').click()
        })

        expect(reload).toHaveBeenCalledTimes(1)
    })
})
