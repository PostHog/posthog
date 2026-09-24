import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Component, Suspense, type ReactNode } from 'react'

import { useRetryableLazy } from 'lib/utils/retryImport'

import { ChunkLoadErrorBoundary } from './ChunkLoadErrorBoundary'

const RELOAD_GUARD_KEY = 'posthog-chunk-reload-at'

class TestErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
    override state: { error: Error | null } = { error: null }

    static getDerivedStateFromError(error: Error): { error: Error } {
        return { error }
    }

    override render(): ReactNode {
        if (this.state.error) {
            return <div>{this.state.error.message}</div>
        }

        return this.props.children
    }
}

function ThrowChunkError(): JSX.Element {
    throw new TypeError('Failed to fetch dynamically imported module: /static/react-json-view.js')
}

// Mirrors a consumer of a chunk the mounted subtree requests later, like the Monaco editor inside
// the feature flag form. The lazy value is real, so React caches its rejection the way it does live.
function LazyChunkConsumer({ factory }: { factory: () => Promise<{ default: () => JSX.Element }> }): JSX.Element {
    const { Lazy, retry } = useRetryableLazy(factory)
    return (
        <ChunkLoadErrorBoundary
            reload={jest.fn()}
            degradeInPlace
            fallback={(_error, clearError) => (
                <button
                    onClick={() => {
                        retry()
                        clearError()
                    }}
                >
                    try again
                </button>
            )}
        >
            <Suspense fallback={<div>loading</div>}>
                <Lazy />
            </Suspense>
        </ChunkLoadErrorBoundary>
    )
}

function ThrowRegularError(): JSX.Element {
    throw new Error('regular render failure')
}

function ThrowGenericNetworkError(): JSX.Element {
    // Same shape a failed import() takes on Safari/Firefox, thrown by an unrelated fetch here.
    throw new TypeError('Load failed')
}

describe('ChunkLoadErrorBoundary', () => {
    let consoleErrorSpy: jest.SpyInstance
    let consoleWarnSpy: jest.SpyInstance

    beforeEach(() => {
        window.localStorage.clear()
        consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
        consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
    })

    afterEach(() => {
        consoleErrorSpy.mockRestore()
        consoleWarnSpy.mockRestore()
        cleanup()
    })

    it('reloads for chunk errors before the parent error boundary catches them', () => {
        const reload = jest.fn()

        render(
            <TestErrorBoundary>
                <ChunkLoadErrorBoundary reload={reload}>
                    <ThrowChunkError />
                </ChunkLoadErrorBoundary>
            </TestErrorBoundary>
        )

        expect(reload).toHaveBeenCalledTimes(1)
        expect(screen.queryByText('Failed to fetch dynamically imported module')).not.toBeInTheDocument()
        expect(Number(window.localStorage.getItem(RELOAD_GUARD_KEY))).toBeGreaterThan(0)
    })

    it('surfaces repeated chunk errors instead of reloading in a loop', () => {
        const reload = jest.fn()
        window.localStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()))

        render(
            <TestErrorBoundary>
                <ChunkLoadErrorBoundary reload={reload}>
                    <ThrowChunkError />
                </ChunkLoadErrorBoundary>
            </TestErrorBoundary>
        )

        expect(reload).not.toHaveBeenCalled()
        expect(
            screen.getByText('Failed to fetch dynamically imported module: /static/react-json-view.js')
        ).toBeInTheDocument()
    })

    it('renders the fallback for repeated chunk errors when one is provided', () => {
        const reload = jest.fn()
        window.localStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()))

        render(
            <TestErrorBoundary>
                <ChunkLoadErrorBoundary
                    reload={reload}
                    fallback={(error) => <div>fallback: {(error as Error).message}</div>}
                >
                    <ThrowChunkError />
                </ChunkLoadErrorBoundary>
            </TestErrorBoundary>
        )

        expect(reload).not.toHaveBeenCalled()
        expect(
            screen.getByText('fallback: Failed to fetch dynamically imported module: /static/react-json-view.js')
        ).toBeInTheDocument()
        expect(
            screen.queryByText('Failed to fetch dynamically imported module: /static/react-json-view.js')
        ).not.toBeInTheDocument()
    })

    it('renders the fallback instead of reloading when the subtree degrades in place', () => {
        const reload = jest.fn()

        render(
            <TestErrorBoundary>
                <ChunkLoadErrorBoundary reload={reload} degradeInPlace fallback={() => <div>keep editing</div>}>
                    <ThrowChunkError />
                </ChunkLoadErrorBoundary>
            </TestErrorBoundary>
        )

        expect(reload).not.toHaveBeenCalled()
        expect(screen.getByText('keep editing')).toBeInTheDocument()
        // Nothing reloaded, so the guard window must stay free for a later genuine reload.
        expect(window.localStorage.getItem(RELOAD_GUARD_KEY)).toBeNull()
    })

    it('requests the chunk again when the fallback retries', async () => {
        let shouldFail = true
        const factory = jest.fn(() =>
            shouldFail
                ? Promise.reject(new TypeError('Failed to fetch dynamically imported module: /static/monaco.js'))
                : Promise.resolve({ default: () => <div>editor loaded</div> })
        )

        render(
            <TestErrorBoundary>
                <LazyChunkConsumer factory={factory} />
            </TestErrorBoundary>
        )

        // retryImport backs off twice before the rejection reaches the boundary.
        const retryButton = await screen.findByText('try again', undefined, { timeout: 5000 })
        const callsBeforeRetry = factory.mock.calls.length

        shouldFail = false
        await act(async () => {
            fireEvent.click(retryButton)
        })

        // React keeps a rejected import, so a retry that only clears the boundary never re-imports
        // and the person stays stuck on the fallback with no way to save.
        await waitFor(() => expect(screen.getByText('editor loaded')).toBeInTheDocument())
        expect(factory.mock.calls.length).toBeGreaterThan(callsBeforeRetry)
    })

    it('lets non-chunk errors bubble to the parent error boundary', () => {
        const reload = jest.fn()

        render(
            <TestErrorBoundary>
                <ChunkLoadErrorBoundary reload={reload}>
                    <ThrowRegularError />
                </ChunkLoadErrorBoundary>
            </TestErrorBoundary>
        )

        expect(reload).not.toHaveBeenCalled()
        expect(screen.getByText('regular render failure')).toBeInTheDocument()
    })

    it('lets an unmarked generic network error bubble instead of reloading', () => {
        const reload = jest.fn()

        render(
            <TestErrorBoundary>
                <ChunkLoadErrorBoundary reload={reload}>
                    <ThrowGenericNetworkError />
                </ChunkLoadErrorBoundary>
            </TestErrorBoundary>
        )

        expect(reload).not.toHaveBeenCalled()
        expect(screen.getByText('Load failed')).toBeInTheDocument()
    })
})
