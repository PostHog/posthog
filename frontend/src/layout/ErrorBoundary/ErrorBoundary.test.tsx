import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { ErrorBoundary } from './ErrorBoundary'

const REMOVE_CHILD_MESSAGE =
    "Failed to execute 'removeChild' on 'Node': The node to be removed is not a child of this node."

let thrownMessage: string | null = REMOVE_CHILD_MESSAGE

function Unstable(): JSX.Element {
    if (thrownMessage) {
        throw new Error(thrownMessage)
    }
    return <div>recovered content</div>
}

describe('ErrorBoundary', () => {
    let consoleErrorSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
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

    // The app-root boundary in scenes/App.tsx has no key to remount it, so without an in-fallback
    // reset a crash outside a scene (nav, command palette) can only be cleared by reloading.
    it('re-renders its children when the user clicks Try again', async () => {
        renderBoundary()
        expect(screen.getByText('An error has occurred')).toBeInTheDocument()

        thrownMessage = null
        await userEvent.click(screen.getByText('Try again'))

        expect(screen.getByText('recovered content')).toBeInTheDocument()
        expect(screen.queryByText('An error has occurred')).not.toBeInTheDocument()
    })

    it.each([
        ['a DOM mutation error', REMOVE_CHILD_MESSAGE, true],
        ['any other error', 'something else broke', false],
    ])('points at page translation for %s: %s', (_description, message, expected) => {
        thrownMessage = message
        renderBoundary()

        expect(!!screen.queryByText(/translation/i)).toBe(expected)
    })
})
