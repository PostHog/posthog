import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { AuthenticatedShellFallback } from './AuthenticatedShellFallback'

describe('AuthenticatedShellFallback', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
        setPageHidden(false)
        jest.restoreAllMocks()
    })

    function setPageHidden(hidden: boolean): void {
        Object.defineProperty(document, 'hidden', { configurable: true, value: hidden })
        document.dispatchEvent(new Event('visibilitychange'))
    }

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

    it('counts only visible time before it shows the reload prompt', () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        setPageHidden(true)
        render(<AuthenticatedShellFallback showSpinner />)

        act(() => {
            jest.advanceTimersByTime(30000)
        })
        expect(screen.queryByText('Reload')).not.toBeInTheDocument()

        act(() => {
            setPageHidden(false)
        })
        act(() => {
            jest.advanceTimersByTime(5000)
        })
        act(() => {
            setPageHidden(true)
        })
        act(() => {
            jest.advanceTimersByTime(30000)
        })
        act(() => {
            setPageHidden(false)
        })
        act(() => {
            jest.advanceTimersByTime(2999)
        })
        expect(screen.queryByText('Reload')).not.toBeInTheDocument()

        act(() => {
            jest.advanceTimersByTime(1)
        })
        expect(screen.getByText('Reload')).toBeInTheDocument()
        expect(capture).toHaveBeenCalledWith(
            'authenticated shell reload prompt shown',
            expect.objectContaining({ page_was_hidden: true })
        )
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
