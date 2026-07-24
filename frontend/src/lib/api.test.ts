import posthog from 'posthog-js'

import api, { ApiConfig, ApiError, ApiRequest } from 'lib/api'

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

    describe('aborted requests', () => {
        it('rethrows a DOMException AbortError as-is', async () => {
            const abortError = new DOMException('unmounting component', 'AbortError')
            fakeFetch.mockRejectedValueOnce(abortError)

            await expect(api.get('/api/projects/2/insights/')).rejects.toBe(abortError)
        })

        it('normalizes a string abort reason into an AbortError instead of an ApiError', async () => {
            // A plain-string abort reason (e.g. `abort('unmounting component')`) has no `.name`, so it
            // must not be wrapped in an ApiError and captured as error-tracking noise.
            fakeFetch.mockRejectedValueOnce('unmounting component')

            await expect(api.get('/api/projects/2/insights/')).rejects.toMatchObject({
                name: 'AbortError',
                message: 'unmounting component',
            })
        })
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

        it('propagates an AbortError instead of masquerading as a null result', async () => {
            const abortError = new DOMException('The operation was aborted', 'AbortError')
            fakeFetch.mockResolvedValue(fakeResponse({ text: () => Promise.reject(abortError) }))
            await expect(api.get('api/environments/2/insights')).rejects.toBe(abortError)
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
