import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { RootErrorBoundary } from './RootErrorBoundary'

function ThrowRenderError(): JSX.Element {
    throw new Error('boot render kaboom')
}

function ThrowChunkError(): JSX.Element {
    throw new TypeError('Failed to fetch dynamically imported module: /static/chunk-App.js')
}

describe('RootErrorBoundary', () => {
    let consoleErrorSpy: jest.SpyInstance
    let sendBeacon: jest.Mock

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
        delete window.JS_POSTHOG_API_KEY
        delete window.JS_POSTHOG_HOST
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

    it('does not report when capture is opted out', () => {
        delete window.JS_POSTHOG_API_KEY

        render(
            <RootErrorBoundary>
                <ThrowRenderError />
            </RootErrorBoundary>
        )

        expect(screen.getByRole('alert')).toBeInTheDocument()
        expect(sendBeacon).not.toHaveBeenCalled()
    })
})
