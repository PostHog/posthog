import posthog from 'posthog-js'

import api, { ApiRequest } from 'lib/api'

import { PropertyFilterType, PropertyOperator } from '~/types'

describe('API helper', () => {
    let fakeFetch: jest.Mock<any, any>

    const FAKE_FETCH_RESULT = ['fake API result']

    beforeEach(() => {
        fakeFetch = jest.fn()
        fakeFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(FAKE_FETCH_RESULT) })
        window.fetch = fakeFetch

        jest.spyOn(posthog, 'capture').mockImplementation(() => {
            return undefined
        })
        jest.spyOn(posthog, 'get_session_id').mockReturnValue('fake-session-id')
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

        const verbs = ['get', 'update', 'create', 'delete']

        verbs.forEach((verb) => {
            testCases.forEach((testCase) => {
                it(`when API is using verb ${verb} it normalizes ${testCase.url} to ${testCase.expected}`, () => {
                    api[verb](testCase.url)
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
