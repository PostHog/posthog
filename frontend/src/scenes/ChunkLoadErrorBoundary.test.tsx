import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Component, type ReactNode } from 'react'

import { APP_RELOAD_EVENT } from 'lib/utils/captureAppReload'

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
        delete window.posthog
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

    it('captures an event for the reload, so the recovery is visible outside session recordings', () => {
        const capture = jest.fn()
        window.posthog = { capture } as any

        render(
            <TestErrorBoundary>
                <ChunkLoadErrorBoundary reload={jest.fn()}>
                    <ThrowChunkError />
                </ChunkLoadErrorBoundary>
            </TestErrorBoundary>
        )

        expect(capture).toHaveBeenCalledWith(
            APP_RELOAD_EVENT,
            expect.objectContaining({ reason: 'chunk_load_error_boundary' }),
            expect.anything()
        )
    })

    it('reloads even when capturing the event fails', () => {
        const reload = jest.fn()
        window.posthog = {
            capture: jest.fn(() => {
                throw new Error('SDK capture blew up')
            }),
        } as any

        render(
            <TestErrorBoundary>
                <ChunkLoadErrorBoundary reload={reload}>
                    <ThrowChunkError />
                </ChunkLoadErrorBoundary>
            </TestErrorBoundary>
        )

        expect(reload).toHaveBeenCalledTimes(1)
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
