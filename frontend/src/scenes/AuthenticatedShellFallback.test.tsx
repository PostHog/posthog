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

    it('holds the reload prompt back until the shell load is clearly stuck', () => {
        render(<AuthenticatedShellFallback />)

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

        render(<AuthenticatedShellFallback />)
        act(() => {
            jest.advanceTimersByTime(8000)
        })

        act(() => {
            screen.getByText('Reload').click()
        })

        expect(reload).toHaveBeenCalledTimes(1)
    })
})
