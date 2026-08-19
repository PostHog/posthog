import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { Component, type ReactNode } from 'react'

import { ChunkLoadErrorBoundary } from 'scenes/ChunkLoadErrorBoundary'

import { RootErrorBoundary } from '~/RootErrorBoundary'
import { initKeaTests } from '~/test/init'

import { ErrorBoundary } from './ErrorBoundary'

class ParentBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
    override state: { error: Error | null } = { error: null }

    static getDerivedStateFromError(error: Error): { error: Error } {
        return { error }
    }

    override render(): ReactNode {
        if (this.state.error) {
            return <div>parent caught: {this.state.error.message}</div>
        }
        return this.props.children
    }
}

function Throw({ error }: { error: Error }): JSX.Element {
    throw error
}

describe('ErrorBoundary', () => {
    let consoleErrorSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
    })

    afterEach(() => {
        consoleErrorSpy.mockRestore()
        window.localStorage.clear()
        cleanup()
    })

    it('rethrows a chunk-load error so an outer boundary can recover it', () => {
        const chunkError = new TypeError('error loading dynamically imported module: /static/WebVitals.js')

        render(
            <Provider>
                <ParentBoundary>
                    <ErrorBoundary>
                        <Throw error={chunkError} />
                    </ErrorBoundary>
                </ParentBoundary>
            </Provider>
        )

        expect(screen.getByText(/parent caught/)).toBeInTheDocument()
        expect(screen.queryByText('An error has occurred')).not.toBeInTheDocument()
    })

    it('renders the error panel for a regular error', () => {
        render(
            <Provider>
                <ParentBoundary>
                    <ErrorBoundary>
                        <Throw error={new Error('regular render failure')} />
                    </ErrorBoundary>
                </ParentBoundary>
            </Provider>
        )

        expect(screen.getByText('An error has occurred')).toBeInTheDocument()
        expect(screen.queryByText(/parent caught/)).not.toBeInTheDocument()
    })

    it('recovers a chunk error surfacing after a recent reload via the terminal RootErrorBoundary', () => {
        // Mirrors the standalone-root stack (exporter/index.tsx, render-query/index.tsx). A second
        // chunk failure inside the 20s guard window makes ChunkLoadErrorBoundary surface (rethrow)
        // the error, and the shared ErrorBoundary rethrows it too, so without a terminal boundary
        // the tree would unmount and blank the frame. RootErrorBoundary must catch it instead.
        window.localStorage.setItem('posthog-chunk-reload-at', String(Date.now()))
        const chunkError = new TypeError('Failed to fetch dynamically imported module: /static/WebVitals.js')

        render(
            <Provider>
                <RootErrorBoundary>
                    <ErrorBoundary>
                        <ChunkLoadErrorBoundary reload={jest.fn()}>
                            <Throw error={chunkError} />
                        </ChunkLoadErrorBoundary>
                    </ErrorBoundary>
                </RootErrorBoundary>
            </Provider>
        )

        expect(screen.getByRole('alert')).toHaveTextContent('PostHog failed to load.')
        expect(screen.queryByText('An error has occurred')).not.toBeInTheDocument()
    })
})
