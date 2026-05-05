import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'

import * as chunkLoadErrorRecovery from 'lib/utils/chunkLoadErrorRecovery'

import { initKeaTests } from '~/test/init'

import { ErrorBoundary } from './ErrorBoundary'

function ThrowChunkLoadError(): never {
    throw new Error('Failed to fetch dynamically imported module: /static/chunk.js')
}

describe('ErrorBoundary', () => {
    let consoleErrorSpy: jest.SpyInstance
    let reloadAfterChunkLoadErrorSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        chunkLoadErrorRecovery.clearChunkLoadReloadAttempt()
        consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => undefined)
        reloadAfterChunkLoadErrorSpy = jest
            .spyOn(chunkLoadErrorRecovery, 'reloadAfterChunkLoadError')
            .mockImplementation(() => undefined)
    })

    afterEach(() => {
        cleanup()
        consoleErrorSpy.mockRestore()
        reloadAfterChunkLoadErrorSpy.mockRestore()
    })

    it('reloads once for a chunk load error before showing the generic fallback', async () => {
        render(
            <ErrorBoundary>
                <ThrowChunkLoadError />
            </ErrorBoundary>
        )

        expect(await screen.findByText('Refreshing…')).toBeInTheDocument()

        await waitFor(() => {
            expect(reloadAfterChunkLoadErrorSpy).toHaveBeenCalledTimes(1)
        })

        expect(screen.queryByText('An error has occurred')).not.toBeInTheDocument()
    })

    it('shows the network error state after a recent reload attempt', async () => {
        chunkLoadErrorRecovery.markChunkLoadReloadAttempt()

        render(
            <ErrorBoundary>
                <ThrowChunkLoadError />
            </ErrorBoundary>
        )

        expect(await screen.findByText('Network error')).toBeInTheDocument()
        expect(screen.getByText('There was an issue loading the requested resource.')).toBeInTheDocument()
        expect(reloadAfterChunkLoadErrorSpy).not.toHaveBeenCalled()
        expect(screen.queryByText('An error has occurred')).not.toBeInTheDocument()
    })
})
