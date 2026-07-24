import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { ChunkLoadErrorBoundary } from 'scenes/ChunkLoadErrorBoundary'

import { initKeaTests } from '~/test/init'

import { ErrorBoundary, LightErrorBoundary } from './ErrorBoundary'

function ThrowChunkError(): JSX.Element {
    throw new TypeError('Failed to fetch dynamically imported module: /static/react-json-view.js')
}

function ThrowRegularError(): JSX.Element {
    throw new Error('regular render failure')
}

describe('ErrorBoundary chunk-load recovery', () => {
    let consoleErrorSpy: jest.SpyInstance
    let consoleWarnSpy: jest.SpyInstance
    let captureExceptionSpy: jest.SpyInstance

    beforeEach(() => {
        window.localStorage.clear()
        initKeaTests()
        consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
        consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
        captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
    })

    afterEach(() => {
        consoleErrorSpy.mockRestore()
        consoleWarnSpy.mockRestore()
        captureExceptionSpy.mockRestore()
        cleanup()
    })

    it.each([
        ['ErrorBoundary', ErrorBoundary],
        ['LightErrorBoundary', LightErrorBoundary],
    ])('%s rethrows chunk-load errors to the ChunkLoadErrorBoundary above, after capturing', (_name, Boundary) => {
        const reload = jest.fn()

        render(
            <ChunkLoadErrorBoundary reload={reload}>
                <Boundary>
                    <ThrowChunkError />
                </Boundary>
            </ChunkLoadErrorBoundary>
        )

        expect(reload).toHaveBeenCalledTimes(1)
        expect(captureExceptionSpy).toHaveBeenCalledTimes(1)
        expect(screen.queryByText(/Failed to fetch dynamically imported module/)).not.toBeInTheDocument()
    })

    it.each([
        ['ErrorBoundary', ErrorBoundary],
        ['LightErrorBoundary', LightErrorBoundary],
    ])('%s renders its error UI for chunk-load errors when no ChunkLoadErrorBoundary is above', (_name, Boundary) => {
        render(
            <Boundary>
                <ThrowChunkError />
            </Boundary>
        )

        expect(screen.getByText(/Failed to fetch dynamically imported module/)).toBeInTheDocument()
    })

    it('renders the error UI for non-chunk errors instead of rethrowing', () => {
        const reload = jest.fn()

        render(
            <ChunkLoadErrorBoundary reload={reload}>
                <ErrorBoundary>
                    <ThrowRegularError />
                </ErrorBoundary>
            </ChunkLoadErrorBoundary>
        )

        expect(reload).not.toHaveBeenCalled()
        expect(screen.getByText('An error has occurred')).toBeInTheDocument()
    })
})
