import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { markChunkFailureReload } from 'lib/utils/chunkReloadGuard'

import { AuthenticatedShellFallback } from './AuthenticatedShellFallback'

jest.mock('posthog-js', () => ({ __esModule: true, default: { capture: jest.fn() } }))

describe('AuthenticatedShellFallback', () => {
    let reload: jest.Mock

    beforeEach(() => {
        jest.useFakeTimers()
        jest.mocked(posthog.capture).mockClear()
        window.localStorage.clear()
        reload = jest.fn()
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: { ...window.location, reload },
        })
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

    it('reloads on its own once the shell load is clearly stuck', () => {
        render(<AuthenticatedShellFallback showSpinner />)

        act(() => {
            jest.advanceTimersByTime(2000)
        })
        expect(reload).not.toHaveBeenCalled()

        act(() => {
            jest.advanceTimersByTime(6000)
        })
        expect(reload).toHaveBeenCalledTimes(1)
        expect(posthog.capture).toHaveBeenCalledWith(
            'app shell load stalled',
            expect.objectContaining({ auto_reloaded: true }),
            expect.anything()
        )
    })

    it('offers a manual reload instead of reloading again after a recent reload', () => {
        markChunkFailureReload()
        render(<AuthenticatedShellFallback showSpinner />)

        act(() => {
            jest.advanceTimersByTime(8000)
        })

        expect(reload).not.toHaveBeenCalled()
        expect(posthog.capture).toHaveBeenCalledWith(
            'app shell load stalled',
            expect.objectContaining({ auto_reloaded: false }),
            expect.anything()
        )
        expect(screen.getByText('Reload')).toBeInTheDocument()

        act(() => {
            screen.getByText('Reload').click()
        })
        expect(reload).toHaveBeenCalledTimes(1)
    })
})
