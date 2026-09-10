import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { ErrorBoundary } from './ErrorBoundary'

const REMOVE_CHILD_MESSAGE =
    "Failed to execute 'removeChild' on 'Node': The node to be removed is not a child of this node."

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
    let consoleErrorSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        renderAttempts = 0
        throwUntilAttempt = 0
        thrownMessage = REMOVE_CHILD_MESSAGE
        consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
    })

    afterEach(() => {
        cleanup()
        consoleErrorSpy.mockRestore()
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
