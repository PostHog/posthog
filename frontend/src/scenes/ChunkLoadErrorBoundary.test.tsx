import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { Component, Suspense, lazy, type ReactNode } from 'react'

import { requireBootExport } from 'lib/utils/retryImport'

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

function ThrowRegularError(): JSX.Element {
    throw new Error('regular render failure')
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

    it.each([
        ['the boot chunk arrives without bootApp', { App: () => <div>app</div> }],
        ['the app chunk arrives without App', { bootApp: () => {} }],
    ])('reloads when %s', async (_label, staleChunk) => {
        const reload = jest.fn()
        // The shape of the entry's lazy factory (frontend/src/index.tsx) against a stale chunk:
        // the module loads, but an export the boot path needs is gone.
        const StaleApp = lazy(() =>
            Promise.resolve<{ bootApp?: () => void; App?: () => JSX.Element }>(staleChunk).then((module) => {
                const bootApp = requireBootExport(module, 'bootApp')
                const AppComponent = requireBootExport(module, 'App')
                bootApp()
                return { default: AppComponent }
            })
        )

        await act(async () => {
            render(
                <TestErrorBoundary>
                    <ChunkLoadErrorBoundary reload={reload}>
                        <Suspense fallback={<div>loading</div>}>
                            <StaleApp />
                        </Suspense>
                    </ChunkLoadErrorBoundary>
                </TestErrorBoundary>
            )
        })

        expect(reload).toHaveBeenCalledTimes(1)
        expect(screen.queryByText(/resolved without its/)).not.toBeInTheDocument()
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
})
