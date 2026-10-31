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
    const initialUrl = window.location.href
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
        delete window.POSTHOG_USER_IDENTITY_WITH_FLAGS
        window.localStorage.removeItem('ph_test-api-key_posthog')
        document.cookie = 'ph_test-api-key_posthog=; max-age=0; path=/'
        window.history.replaceState({}, '', initialUrl)
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

    it.each(['control', 'test'])('keeps the %s login assignment on a boot failure', (variant) => {
        document.body.insertAdjacentHTML('beforeend', '<a id="login-entry-recovery" href="/login">Recovery</a>')
        window.localStorage.setItem(
            'ph_test-api-key_posthog',
            JSON.stringify({ distinct_id: 'synthetic-person', $device_id: 'synthetic-device' })
        )
        window.POSTHOG_USER_IDENTITY_WITH_FLAGS = { featureFlags: { 'standalone-login-entry': variant } }
        render(
            <RootErrorBoundary fallbackHref="/login?next=%2Fproject&auth_app=fallback">
                <ThrowChunkError />
            </RootErrorBoundary>
        )
        expect(screen.getByRole('link')).toHaveAttribute('href', '/login?next=%2Fproject&auth_app=fallback')
        expect(document.getElementById('login-entry-recovery')).toBeNull()
        const event = JSON.parse(sendBeacon.mock.calls[0][1])
        expect(event.distinct_id).toBe('synthetic-person')
        expect(event.properties.$device_id).toBe('synthetic-device')
        expect(event.properties['$feature/standalone-login-entry']).toBe(variant)
    })

    it('uses the analytics cookie when local storage has no identity', () => {
        document.cookie = `ph_test-api-key_posthog=${encodeURIComponent(
            JSON.stringify({ distinct_id: 'synthetic-cookie-person', $device_id: 'synthetic-cookie-device' })
        )}; path=/`
        render(
            <RootErrorBoundary>
                <ThrowRenderError />
            </RootErrorBoundary>
        )

        const event = JSON.parse(sendBeacon.mock.calls[0][1])
        expect(event.distinct_id).toBe('synthetic-cookie-person')
        expect(event.properties.$device_id).toBe('synthetic-cookie-device')
    })

    it.each([
        { variant: 'control', path: '/login', cookie: 'valid', expected: 'cookie' },
        { variant: 'test', path: '/login/', cookie: 'valid', expected: 'cookie' },
        { variant: false, path: '/login', cookie: 'valid', expected: 'local' },
        { variant: 'test', path: '/project/1', cookie: 'valid', expected: 'local' },
        { variant: 'test', path: '/login', cookie: 'missing', expected: 'local' },
        { variant: 'test', path: '/login', cookie: 'invalid', expected: 'local' },
    ])('uses $expected identity for $variant at $path with $cookie cookie', ({ variant, path, cookie, expected }) => {
        window.history.replaceState({}, '', path)
        window.POSTHOG_USER_IDENTITY_WITH_FLAGS = { featureFlags: { 'standalone-login-entry': variant } }
        window.localStorage.setItem(
            'ph_test-api-key_posthog',
            JSON.stringify({ distinct_id: 'synthetic-local-person', $device_id: 'synthetic-local-device' })
        )
        if (cookie !== 'missing') {
            const value =
                cookie === 'valid'
                    ? encodeURIComponent(
                          JSON.stringify({
                              distinct_id: 'synthetic-cookie-person',
                              $device_id: 'synthetic-cookie-device',
                          })
                      )
                    : 'invalid-json'
            document.cookie = `ph_test-api-key_posthog=${value}; path=/`
        }
        render(
            <RootErrorBoundary>
                <ThrowRenderError />
            </RootErrorBoundary>
        )
        const event = JSON.parse(sendBeacon.mock.calls[0][1])
        expect(event.distinct_id).toBe(`synthetic-${expected}-person`)
        expect(event.properties.$device_id).toBe(`synthetic-${expected}-device`)
    })

    it.each([
        ['login with nested next URL', '/login?next=%2Freset%3Ftoken%3Dexample#section', '/login'],
        ['login with nested reset URL', '/login/?reset=%2Freset%3Ftoken%3Dexample#section', '/login/'],
        ['other page', '/project/1?next=%2Fproject%2F2#section', '/project/1?next=%2Fproject%2F2#section'],
        ['other page with metric variables', '/dashboard?metricVariables=example#section', '/dashboard'],
    ])('reports a %s boot URL safely', (_case, url, expectedPath) => {
        window.history.replaceState({}, '', url)
        render(
            <RootErrorBoundary>
                <ThrowRenderError />
            </RootErrorBoundary>
        )

        expect(JSON.parse(sendBeacon.mock.calls[0][1]).properties.$current_url).toBe(
            `${window.location.origin}${expectedPath}`
        )
    })
})
