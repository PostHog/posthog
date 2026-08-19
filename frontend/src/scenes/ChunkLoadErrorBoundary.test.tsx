import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Component, type ReactNode } from 'react'

import { ChunkLoadErrorBoundary } from './ChunkLoadErrorBoundary'

const RELOAD_GUARD_KEY = 'posthog-chunk-reload-guard-lazy'

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
        expect(JSON.parse(window.localStorage.getItem(RELOAD_GUARD_KEY) ?? '{}').count).toBe(1)
    })

    it('surfaces the second chunk error even when the reload cycle took longer than 20s', () => {
        const reload = jest.fn()
        // A prior reload 30s ago - past the old 20s window but still within one slow cycle.
        // The counter must surface the error here rather than reload into a loop.
        window.localStorage.setItem(RELOAD_GUARD_KEY, JSON.stringify({ count: 1, at: Date.now() - 30_000 }))

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
