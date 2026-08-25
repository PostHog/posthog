import * as fetchEventSourceModule from '@microsoft/fetch-event-source'
import posthog from 'posthog-js'

import api, { ApiConfig, ApiError, ApiRequest, NetworkError } from 'lib/api'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

// Mirrors SESSION_KEY in lib/oauth/oauthClient — the localStorage key its real getStoredSession reads.
const OAUTH_SESSION_KEY = 'ph_oauth_session'

describe('API helper', () => {
    let fakeFetch: jest.Mock<any, any>

    const FAKE_FETCH_RESULT = ['fake API result']

    beforeEach(() => {
        fakeFetch = jest.fn()
        fakeFetch.mockResolvedValue({
            ok: true,
            status: 200,
            json: () => Promise.resolve(FAKE_FETCH_RESULT),
            text: () => Promise.resolve(JSON.stringify(FAKE_FETCH_RESULT)),
        })
        window.fetch = fakeFetch

        jest.spyOn(posthog, 'capture').mockImplementation(() => {
            return undefined
        })
        jest.spyOn(posthog, 'get_session_id').mockReturnValue('fake-session-id')
        ApiConfig.setCurrentTeamId(2)
    })

    describe('events', () => {
        it('can build URL for events with properties', async () => {
            await api.events.list(
                {
                    properties: [
                        {
                            key: 'something',
                            value: 'is_set',
                            operator: PropertyOperator.IsSet,
                            type: PropertyFilterType.Event,
                        },
                    ],
                },
                10,
                2
            )

            expect(fakeFetch).toHaveBeenCalledWith(
                '/api/environments/2/events?properties=%5B%7B%22key%22%3A%22something%22%2C%22value%22%3A%22is_set%22%2C%22operator%22%3A%22is_set%22%2C%22type%22%3A%22event%22%7D%5D&limit=10&orderBy=%5B%22-timestamp%22%5D',
                {
                    signal: undefined,
                    headers: {
                        'X-POSTHOG-SESSION-ID': 'fake-session-id',
                    },
                }
            )
        })
    })

    describe('dashboard tile streaming', () => {
        it.each([
            { status: 401, body: { detail: 'Authentication expired.' }, expectedCode: null },
            {
                status: 403,
                body: { detail: 'Access denied.', code: 'permission_denied' },
                expectedCode: 'permission_denied',
            },
        ])('preserves status handling for HTTP $status', async ({ status, body, expectedCode }) => {
            const onApiResponse = jest.fn()
            const apiStatusLogicSpy = jest
                .spyOn(apiStatusLogic, 'findMounted')
                .mockReturnValueOnce({ actions: { onApiResponse } } as any)

            const fetchEventSourceSpy = jest
                .spyOn(fetchEventSourceModule, 'fetchEventSource')
                .mockReturnValueOnce(new Promise<void>(() => {}))

            const onError = jest.fn()
            await api.dashboards.streamTiles(5, {}, jest.fn(), jest.fn(), onError)
            expect(fetchEventSourceSpy).toHaveBeenCalledTimes(1)

            const response = new Response(JSON.stringify(body), {
                status,
                headers: { 'Content-Type': 'application/json' },
            })
            await fetchEventSourceSpy.mock.calls[0][1].onopen?.(response)

            expect(onApiResponse).toHaveBeenCalledTimes(1)
            expect(onApiResponse.mock.calls[0][0]).toMatchObject({ status })
            expect(onError).toHaveBeenCalledWith(expect.objectContaining({ status, code: expectedCode }))
            fetchEventSourceSpy.mockRestore()
            apiStatusLogicSpy.mockRestore()
        })

        it('reports connection failures and ignores intentional aborts', async () => {
            const onApiResponse = jest.fn()
            const apiStatusLogicSpy = jest
                .spyOn(apiStatusLogic, 'findMounted')
                .mockReturnValue({ actions: { onApiResponse } } as any)
            const fetchEventSourceSpy = jest
                .spyOn(fetchEventSourceModule, 'fetchEventSource')
                .mockReturnValueOnce(new Promise<void>(() => {}))
            const onError = jest.fn()

            await api.dashboards.streamTiles(5, {}, jest.fn(), jest.fn(), onError)

            const streamOptions = fetchEventSourceSpy.mock.calls[0][1]
            const connectionError = new TypeError('Failed to fetch')
            streamOptions.onerror?.(connectionError)
            expect(onApiResponse).toHaveBeenCalledWith(undefined, connectionError)
            expect(onError).toHaveBeenCalledWith(connectionError)

            const abortError = new DOMException('The operation was aborted', 'AbortError')
            streamOptions.onerror?.(abortError)
            expect(onApiResponse).toHaveBeenCalledTimes(1)
            expect(onError).toHaveBeenCalledTimes(1)

            fetchEventSourceSpy.mockRestore()
            apiStatusLogicSpy.mockRestore()
        })

        it('reports a stream that closes before completion', async () => {
            const fetchEventSourceSpy = jest.spyOn(fetchEventSourceModule, 'fetchEventSource').mockResolvedValueOnce()
            const onError = jest.fn()

            await api.dashboards.streamTiles(5, {}, jest.fn(), jest.fn(), onError)
            await Promise.resolve()

            expect(onError).toHaveBeenCalledWith(
                expect.objectContaining({
                    message: 'Dashboard stream ended before loading finished. Refresh the page.',
                })
            )
            fetchEventSourceSpy.mockRestore()
        })
    })

    describe('query endpoints', () => {
        it('adds query kind to the query URL when present', async () => {
            await api.query({ kind: NodeKind.HogQLQuery, query: 'select 1' })

            expect(fakeFetch.mock.calls[0][0]).toEqual('/api/environments/2/query/HogQLQuery/')
        })

        it('keeps the query URL kind optional', async () => {
            await api.query({} as Record<string, any>)

            expect(fakeFetch.mock.calls[0][0]).toEqual('/api/environments/2/query/')
        })

        it('throws when the query URL kind does not match the request body', async () => {
            await expect(
                api.query(
                    { kind: NodeKind.HogQLQuery, query: 'select 1' },
                    {
                        queryKind: NodeKind.EventsQuery,
                    }
                )
            ).rejects.toThrow('Query kind mismatch')
        })
    })

    describe('getting URLs', () => {
        const testCases = [
            {
                url: 'relative/url',
                expected: '/relative/url/',
            },
            {
                url: '/absolute/url',
                expected: '/absolute/url/',
            },
            {
                url: 'relative/url?with=parameters',
                expected: '/relative/url?with=parameters',
            },
            {
                url: '/absolute/url?with=parameters',
                expected: '/absolute/url?with=parameters',
            },
            {
                url: 'http://some/url',
                expected: 'http://some/url',
            },
            {
                url: 'https://some/url',
                expected: 'https://some/url',
            },
        ]

        const verbs = [
            (url: string) => api.get(url),
            (url: string) => api.update(url, undefined),
            (url: string) => api.create(url, undefined),
            (url: string) => api.delete(url),
        ]

        verbs.forEach((verb) => {
            testCases.forEach((testCase) => {
                it(`when API is using verb ${verb} it normalizes ${testCase.url} to ${testCase.expected}`, () => {
                    verb(testCase.url)
                    expect(fakeFetch.mock.calls[0][0]).toEqual(testCase.expected)
                })
            })
        })
    })

    it('rejects project-based requests with void project ID', async () => {
        await expect(api.get('/api/projects/2/')).resolves.not.toThrow()
        await expect(api.get('/api/projects/089908')).resolves.not.toThrow()
        await expect(api.get('/api/projects/089908?x')).resolves.not.toThrow()
        await expect(api.get('/api/projects/xyz/dings/')).resolves.not.toThrow()
        await expect(api.get('/api/projects/null/')).rejects.toStrictEqual({
            detail: 'Cannot make request - project ID is unknown.',
            status: 0,
        })
        await expect(api.get('/api/projects/null')).rejects.toStrictEqual({
            detail: 'Cannot make request - project ID is unknown.',
            status: 0,
        })
        await expect(api.get('/api/projects/null?x')).rejects.toStrictEqual({
            detail: 'Cannot make request - project ID is unknown.',
            status: 0,
        })
        await expect(api.get('/api/projects/null#x')).rejects.toStrictEqual({
            detail: 'Cannot make request - project ID is unknown.',
            status: 0,
        })
        await expect(api.get('/api/projects/null/dings')).rejects.toStrictEqual({
            detail: 'Cannot make request - project ID is unknown.',
            status: 0,
        })
    })

    it('uses response message as the ApiError message when no detail or error is present', async () => {
        fakeFetch.mockResolvedValueOnce({
            ok: false,
            status: 400,
            statusText: '',
            headers: new Headers(),
            json: () => Promise.resolve({ message: 'Could not fetch schemas from source.' }),
        })

        await expect(
            api.create('/api/projects/2/external_data_sources/source-1/refresh_schemas/')
        ).rejects.toMatchObject({
            message: 'Could not fetch schemas from source.',
            status: 400,
            data: { message: 'Could not fetch schemas from source.' },
        } satisfies Partial<ApiError>)
    })

    describe('OAuth mode auth headers', () => {
        beforeEach(() => {
            window.localStorage.setItem(
                OAUTH_SESSION_KEY,
                JSON.stringify({
                    backendHost: 'https://us.posthog.com',
                    clientId: 'client',
                    accessToken: 'oauth-token',
                    refreshToken: 'refresh',
                    expiresAt: 9999999999999,
                })
            )
        })

        afterEach(() => {
            window.localStorage.removeItem(OAUTH_SESSION_KEY)
        })

        it('attaches the bearer token to requests routed to the OAuth backend host', async () => {
            await api.get('/api/projects/2/insights/')
            const [url, options] = fakeFetch.mock.calls[0]
            expect(url).toEqual('https://us.posthog.com/api/projects/2/insights/')
            expect(options.headers.Authorization).toEqual('Bearer oauth-token')
        })

        it('does not attach the bearer token to same-origin requests left on the local instance', async () => {
            await api.get('/some/local/path')
            const [url, options] = fakeFetch.mock.calls[0]
            expect(url).toEqual('/some/local/path/')
            expect(options.headers.Authorization).toBeUndefined()
        })
    })

    describe('successful response body parsing', () => {
        const fakeResponse = ({ status = 200, text }: { status?: number; text: () => Promise<string> }): any => ({
            ok: true,
            status,
            text,
        })
        const bodyOf =
            (body: string): (() => Promise<string>) =>
            (): Promise<string> =>
                Promise.resolve(body)

        it.each([
            ['an HTML error page from a proxy/CDN', '<html><body>Bad gateway</body></html>'],
            // No content-length header involved: detection must work for chunked/compressed responses
            ['truncated JSON from a response cut mid-stream', '{"results": [1, 2'],
        ])('rejects with a status-less, request-scoped ApiError when the body is %s', async (_desc, body) => {
            fakeFetch.mockResolvedValue(fakeResponse({ text: bodyOf(body) }))
            const error = await api.get('api/environments/2/insights').catch((e) => e)
            expect(error).toBeInstanceOf(ApiError)
            // Method + path so occurrences are triageable in error tracking
            expect(error.message).toContain('[GET /api/environments/2/insights]')
            expect(error.message).toContain('status 200')
            // No `status`: a 2xx on an ApiError would make retry/recovery checks
            // (`status === undefined || status >= 500`) treat this transient failure as a client error
            expect(error.status).toBeUndefined()
        })

        it('carries the actual request method in the malformed-body error', async () => {
            fakeFetch.mockResolvedValue(fakeResponse({ text: bodyOf('<html></html>') }))
            const error = await api.create('api/environments/2/insights', {}).catch((e) => e)
            expect(error.message).toContain('[POST /api/environments/2/insights]')
        })

        it('surfaces a body stream that fails mid-read as an ApiError instead of null', async () => {
            fakeFetch.mockResolvedValue(fakeResponse({ text: () => Promise.reject(new TypeError('network error')) }))
            const error = await api.get('api/environments/2/insights').catch((e) => e)
            expect(error).toBeInstanceOf(ApiError)
            expect(error.status).toBeUndefined()
        })

        it.each([
            ['a 204 No Content response', 204, ''],
            ['an empty 200 body', 200, ''],
            ['a whitespace-only body', 200, ' \n '],
        ])('resolves to null for %s', async (_desc, status, body) => {
            fakeFetch.mockResolvedValue(fakeResponse({ status, text: bodyOf(body) }))
            await expect(api.get('api/environments/2/insights')).resolves.toBeNull()
        })

        it('resolves a 204 to null even when reading its empty body rejects', async () => {
            fakeFetch.mockResolvedValue(
                fakeResponse({ status: 204, text: () => Promise.reject(new TypeError('Load failed')) })
            )
            await expect(api.get('api/projects/2/wizard/sessions/latest/')).resolves.toBeNull()
        })

        it('propagates an AbortError instead of masquerading as a null result', async () => {
            const abortError = new DOMException('The operation was aborted', 'AbortError')
            fakeFetch.mockResolvedValue(fakeResponse({ text: () => Promise.reject(abortError) }))
            await expect(api.get('api/environments/2/insights')).rejects.toBe(abortError)
        })
    })

    describe('requests that never reach the server', () => {
        // `pagehide` sets a module-level flag in lib/api, so clear it after every case instead of
        // letting one test's simulated navigation classify the next test's failure.
        afterEach(() => {
            window.dispatchEvent(new Event('pageshow'))
            window.localStorage.removeItem(OAUTH_SESSION_KEY)
        })

        it.each([
            ['offline', false, 'Network request failed: device is offline'],
            ['network', true, 'Network request failed'],
        ])('classifies a fetch rejection as %s', async (reason, onLine, message) => {
            Object.defineProperty(window.navigator, 'onLine', { value: onLine, configurable: true })
            fakeFetch.mockRejectedValue(new TypeError('Failed to fetch'))

            const error = await api.get('api/environments/2/insights').catch((e) => e)

            expect(error).toBeInstanceOf(NetworkError)
            expect(error.reason).toBe(reason)
            // The message is the only channel the reason has: the automatic unhandled-rejection
            // capture carries no custom properties, so `before_send` and grouping rules match on it
            expect(error.message).toBe(message)
            // Recovery paths across the app read `status === undefined` as "transient, may be retried"
            expect(error.status).toBeUndefined()
        })

        it('classifies a fetch rejection during page teardown as navigating', async () => {
            window.dispatchEvent(new Event('pagehide'))
            fakeFetch.mockRejectedValue(new TypeError('Failed to fetch'))

            const error = await api.get('api/environments/2/insights').catch((e) => e)

            expect(error).toMatchObject({ reason: 'navigating' })
        })

        it('reports the failure as a client_request_failure naming the endpoint', async () => {
            fakeFetch.mockRejectedValue(new TypeError('Failed to fetch'))

            await api.get('api/environments/2/insights').catch(() => null)

            expect(posthog.capture).toHaveBeenCalledWith(
                'client_request_failure',
                expect.objectContaining({
                    pathname: '/api/environments/2/insights/',
                    method: 'GET',
                    // 0 keeps these separable from failures that did come back with an HTTP status
                    status: 0,
                    failure_reason: 'network',
                })
            )
        })

        it('still classifies the failure when the request URL cannot be parsed', async () => {
            // `backendHost` comes straight from localStorage, so an out-of-range port reaches the
            // request URL, and `fetch` rejects it with a TypeError. Deriving the pathname must not
            // throw on the same URL, which would replace the classified failure with a crash.
            window.localStorage.setItem(
                OAUTH_SESSION_KEY,
                JSON.stringify({
                    backendHost: 'https://:99999',
                    clientId: 'client',
                    accessToken: 'oauth-token',
                    refreshToken: 'refresh',
                    expiresAt: 9999999999999,
                })
            )
            fakeFetch.mockRejectedValue(new TypeError('Failed to parse URL'))

            const error = await api.get('/api/projects/2/insights/').catch((e) => e)

            expect(error).toBeInstanceOf(NetworkError)
        })

        it('classifies a cross-realm fetch failure that fails instanceof TypeError', async () => {
            // A TypeError thrown in another realm (an iframe) or a `fetch` swapped by a browser
            // extension fails `instanceof TypeError`, so matching only on the class would drop it
            // to an unclassified per-endpoint ApiError. Match the name and known message instead.
            const crossRealmError = { name: 'TypeError', message: 'Failed to fetch' }
            fakeFetch.mockRejectedValue(crossRealmError)

            const error = await api.get('api/environments/2/insights').catch((e) => e)

            expect(error).toBeInstanceOf(NetworkError)
        })

        it('leaves a throw that is not a fetch failure as an unclassified ApiError', async () => {
            // A real fault in the request path must not be relabelled as connectivity, or
            // `dropUnactionableNetworkExceptions` would filter it out of error tracking.
            fakeFetch.mockRejectedValue(new Error('the fetcher itself broke'))

            const error = await api.get('api/environments/2/insights').catch((e) => e)

            expect(error).toBeInstanceOf(ApiError)
            expect(error).not.toBeInstanceOf(NetworkError)
        })
    })

    describe('organizationFeatureFlags', () => {
        it('builds correct URL for organization feature flags', () => {
            const apiRequest = new ApiRequest()
            const request = apiRequest.organizationFeatureFlags('123', 'my-feature-flag')
            expect(request.assembleEndpointUrl()).toEqual('organizations/123/feature_flags/my-feature-flag')
        })

        it('builds correct URL for organization feature flags with special characters', () => {
            const apiRequest = new ApiRequest()
            const request = apiRequest.organizationFeatureFlags('123', 'my-feature-flag/foo/bar?baz=qux')
            expect(request.assembleEndpointUrl()).toEqual(
                'organizations/123/feature_flags/my-feature-flag%2Ffoo%2Fbar%3Fbaz%3Dqux'
            )
        })
    })
})
