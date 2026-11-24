import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { RootErrorBoundary } from './RootErrorBoundary'

function ThrowRenderError(): JSX.Element {
    throw new Error('boot render kaboom')
}

function ThrowNull(): JSX.Element {
    throw null
}

function ThrowChunkError(): JSX.Element {
    throw new TypeError('Failed to fetch dynamically imported module: /static/chunk-App.js')
}

describe('RootErrorBoundary', () => {
    let consoleErrorSpy: jest.SpyInstance
    let sendBeacon: jest.Mock
    const originalFetch = window.fetch

    beforeEach(() => {
        consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
        sendBeacon = jest.fn().mockReturnValue(true)
        Object.defineProperty(window.navigator, 'sendBeacon', {
            value: sendBeacon,
            configurable: true,
            writable: true,
        })
        window.JS_POSTHOG_API_KEY = 'test-api-key'
        window.JS_POSTHOG_HOST = 'https://us.example.com'
    })

    afterEach(() => {
        consoleErrorSpy.mockRestore()
        Object.defineProperty(window, 'fetch', { value: originalFetch, configurable: true, writable: true })
        delete window.JS_POSTHOG_API_KEY
        delete window.JS_POSTHOG_HOST
        delete window.IMPERSONATED_SESSION
        window.history.replaceState({}, '', '/')
        cleanup()
    })

    it('renders children and reports nothing when nothing throws', () => {
        render(
            <RootErrorBoundary>
                <div>app content</div>
            </RootErrorBoundary>
        )

        expect(screen.getByText('app content')).toBeInTheDocument()
        expect(sendBeacon).not.toHaveBeenCalled()
    })

    it('reports render crashes to the capture API and shows crash copy', () => {
        window.history.replaceState({}, '', '/reset/user-uuid/reset-t0k3n?metric_prefill=private-sql')

        render(
            <RootErrorBoundary>
                <ThrowRenderError />
            </RootErrorBoundary>
        )

        expect(screen.getByRole('alert')).toHaveTextContent('PostHog crashed while starting.')
        expect(sendBeacon).toHaveBeenCalledTimes(1)
        const [url, body] = sendBeacon.mock.calls[0]
        expect(url).toBe('https://us.example.com/e/')
        const event = JSON.parse(body)
        expect(event.api_key).toBe('test-api-key')
        expect(event.event).toBe('$exception')
        expect(event.distinct_id).toEqual(expect.any(String))
        expect(event.properties.$exception_list[0].value).toBe('boot render kaboom')
        expect(event.properties.chunk_load_error).toBe(false)
        // The path can carry a reset token, so the report keeps the origin only.
        expect(event.properties.$current_url).toBe('http://localhost')
        expect(body).not.toContain('reset-t0k3n')
        expect(body).not.toContain('private-sql')
    })

    it('reports through fetch when sendBeacon throws', () => {
        sendBeacon.mockImplementation(() => {
            throw new Error('Transport unavailable')
        })
        const fetchMock = jest.fn().mockResolvedValue(undefined)
        Object.defineProperty(window, 'fetch', { value: fetchMock, configurable: true, writable: true })

        render(
            <RootErrorBoundary>
                <ThrowRenderError />
            </RootErrorBoundary>
        )

        expect(fetchMock).toHaveBeenCalledTimes(1)
        const [url, init] = fetchMock.mock.calls[0]
        expect(url).toBe('https://us.example.com/e/')
        expect(JSON.parse(init.body).properties.$exception_list[0].value).toBe('boot render kaboom')
    })

    it('shows crash copy when a component throws null', () => {
        render(
            <RootErrorBoundary>
                <ThrowNull />
            </RootErrorBoundary>
        )

        expect(screen.getByRole('alert')).toHaveTextContent('PostHog crashed while starting.')
        expect(JSON.parse(sendBeacon.mock.calls[0][1]).properties.$exception_list[0].value).toBe('null')
    })

    it('shows load-failure copy for chunk-load errors', () => {
        render(
            <RootErrorBoundary>
                <ThrowChunkError />
            </RootErrorBoundary>
        )

        expect(screen.getByRole('alert')).toHaveTextContent('PostHog failed to load.')
        expect(JSON.parse(sendBeacon.mock.calls[0][1]).properties.chunk_load_error).toBe(true)
    })

    it.each([
        ['capture is opted out', () => delete window.JS_POSTHOG_API_KEY],
        ['the session is impersonated', () => (window.IMPERSONATED_SESSION = true)],
    ])('does not report when %s', (_case, optOut) => {
        optOut()

        render(
            <RootErrorBoundary>
                <ThrowRenderError />
            </RootErrorBoundary>
        )

        expect(screen.getByRole('alert')).toBeInTheDocument()
        expect(sendBeacon).not.toHaveBeenCalled()
    })
})
