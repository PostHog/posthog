import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { ErrorBoundary } from './ErrorBoundary'

const REMOVE_CHILD_MESSAGE =
    "Failed to execute 'removeChild' on 'Node': The node to be removed is not a child of this node."
const CHUNK_LOAD_MESSAGE = 'Failed to fetch dynamically imported module: /static/QueryWidget.js'
const RELOAD_GUARD_KEY = 'posthog-chunk-reload-at'

let renderAttempts = 0
let throwUntilAttempt = 0
let thrownMessage = REMOVE_CHILD_MESSAGE

/**
 * Throws on every render attempt up to `throwUntilAttempt`. React retries a failed render twice
 * before it gives the error to a boundary, so three throws is the smallest count that reaches one.
 */
function Unstable(): JSX.Element {
    renderAttempts += 1
    if (renderAttempts <= throwUntilAttempt) {
        throw new Error(thrownMessage)
    }
    return <div>recovered content</div>
}

describe('ErrorBoundary', () => {
    const originalLocation = window.location
    let consoleErrorSpy: jest.SpyInstance
    let consoleWarnSpy: jest.SpyInstance
    let reloadSpy: jest.Mock

    beforeEach(() => {
        initKeaTests()
        renderAttempts = 0
        throwUntilAttempt = 0
        thrownMessage = REMOVE_CHILD_MESSAGE
        window.localStorage.clear()
        consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
        consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
        reloadSpy = jest.fn()
        Object.defineProperty(window, 'location', {
            value: { ...originalLocation, reload: reloadSpy },
            configurable: true,
        })
    })

    afterEach(() => {
        cleanup()
        consoleErrorSpy.mockRestore()
        consoleWarnSpy.mockRestore()
        Object.defineProperty(window, 'location', { value: originalLocation, configurable: true })
    })

    function renderBoundary(): void {
        render(
            <Provider>
                <ErrorBoundary>
                    <Unstable />
                </ErrorBoundary>
            </Provider>
        )
    }

    // A translated page throws on the commit that touches a replaced text node, and a fresh render
    // of the same subtree succeeds. Before the remount, that one commit cost the user the scene.
    it('remounts its children after a DOM mutation error, with no crash screen', async () => {
        throwUntilAttempt = 3
        renderBoundary()

        expect(await screen.findByText('recovered content')).toBeInTheDocument()
        expect(screen.queryByText('An error has occurred')).not.toBeInTheDocument()
    })

    it('stops remounting and shows the fallback when the DOM mutation error repeats', async () => {
        throwUntilAttempt = Number.POSITIVE_INFINITY
        renderBoundary()

        expect(await screen.findByText('An error has occurred')).toBeInTheDocument()
        expect(screen.getByText(/translation/i)).toBeInTheDocument()
        // A remount loop against a subtree that always throws would never reach that fallback.
        expect(renderAttempts).toBeLessThan(20)
    })

    it('shows the fallback at once for an error that is not a DOM mutation', () => {
        thrownMessage = 'something else broke'
        throwUntilAttempt = 3
        renderBoundary()

        expect(screen.getByText('An error has occurred')).toBeInTheDocument()
        expect(screen.queryByText(/translation/i)).not.toBeInTheDocument()
    })

    // A stale-deploy chunk is gone until the page reloads, so the reporter must not take the error
    // and park the subtree on the crash screen. Before this, a panel that mounts its own boundary
    // kept the dead view and captured the same failure on every remount.
    it('reloads once for a chunk-load error instead of showing the crash screen', () => {
        thrownMessage = CHUNK_LOAD_MESSAGE
        throwUntilAttempt = 3
        renderBoundary()

        expect(reloadSpy).toHaveBeenCalledTimes(1)
        expect(screen.queryByText('An error has occurred')).not.toBeInTheDocument()
    })

    it('asks the user to reload when the chunk-load error survives a reload', () => {
        window.localStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()))
        thrownMessage = CHUNK_LOAD_MESSAGE
        throwUntilAttempt = 3
        renderBoundary()

        expect(reloadSpy).not.toHaveBeenCalled()
        expect(screen.getByText(/part of it could not load/)).toBeInTheDocument()
        expect(screen.queryByText('An error has occurred')).not.toBeInTheDocument()
    })

    // The app-root boundary in scenes/App.tsx has no key to remount it, so without an in-fallback
    // reset a crash outside a scene (nav, command palette) can only be cleared by a reload.
    it('re-renders its children when the user clicks Try again', async () => {
        thrownMessage = 'something else broke'
        throwUntilAttempt = 3
        renderBoundary()
        expect(screen.getByText('An error has occurred')).toBeInTheDocument()

        await userEvent.click(screen.getByText('Try again'))

        expect(screen.getByText('recovered content')).toBeInTheDocument()
        expect(screen.queryByText('An error has occurred')).not.toBeInTheDocument()
    })
})
