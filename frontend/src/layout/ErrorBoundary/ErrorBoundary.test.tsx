import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useEffect } from 'react'

import { PostHogContext } from '@posthog/react'

import { initKeaTests } from '~/test/init'

import { ErrorBoundary } from './ErrorBoundary'

let shouldThrow = true

function MaybeThrow(): JSX.Element {
    if (shouldThrow) {
        throw new Error('boom')
    }
    return <div>healthy content</div>
}

function MountCounter({ onMount }: { onMount: () => void }): JSX.Element {
    useEffect(() => {
        onMount()
    }, [onMount])
    return <div>healthy content</div>
}

const fakeClient = { captureException: jest.fn(() => ({ uuid: 'test-uuid' })) } as any

function renderWithClient(ui: JSX.Element): ReturnType<typeof render> {
    return render(<PostHogContext.Provider value={{ client: fakeClient }}>{ui}</PostHogContext.Provider>)
}

describe('ErrorBoundary', () => {
    let consoleErrorSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        shouldThrow = true
        consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
    })

    afterEach(() => {
        consoleErrorSpy.mockRestore()
        cleanup()
    })

    it('recovers from a caught error when resetKeys change and the child stops throwing', () => {
        const { rerender } = renderWithClient(
            <ErrorBoundary resetKeys={['v1']}>
                <MaybeThrow />
            </ErrorBoundary>
        )
        expect(screen.getByText('An error has occurred')).toBeInTheDocument()

        shouldThrow = false
        rerender(
            <PostHogContext.Provider value={{ client: fakeClient }}>
                <ErrorBoundary resetKeys={['v2']}>
                    <MaybeThrow />
                </ErrorBoundary>
            </PostHogContext.Provider>
        )

        expect(screen.getByText('healthy content')).toBeInTheDocument()
        expect(screen.queryByText('An error has occurred')).not.toBeInTheDocument()
    })

    it('stays on the fallback while resetKeys are unchanged', () => {
        renderWithClient(
            <ErrorBoundary resetKeys={['v1']}>
                <MaybeThrow />
            </ErrorBoundary>
        )
        expect(screen.getByText('An error has occurred')).toBeInTheDocument()

        // A re-render that does not change resetKeys must not clear the error.
        shouldThrow = false
        screen.getByText('An error has occurred')
        expect(screen.queryByText('healthy content')).not.toBeInTheDocument()
    })

    it('does not remount healthy children when resetKeys change', () => {
        shouldThrow = false
        const onMount = jest.fn()

        const { rerender } = renderWithClient(
            <ErrorBoundary resetKeys={['v1']}>
                <MountCounter onMount={onMount} />
            </ErrorBoundary>
        )
        expect(onMount).toHaveBeenCalledTimes(1)

        rerender(
            <PostHogContext.Provider value={{ client: fakeClient }}>
                <ErrorBoundary resetKeys={['v2']}>
                    <MountCounter onMount={onMount} />
                </ErrorBoundary>
            </PostHogContext.Provider>
        )

        // Healthy subtree must not remount just because the reset key changed.
        expect(onMount).toHaveBeenCalledTimes(1)
    })
})
