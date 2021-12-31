import api from 'lib/api'
import { PropertyOperator } from '~/types'

describe('API helper', () => {
    let fakeFetch: jest.Mock<any, any>

    beforeEach(() => {
        fakeFetch = jest.fn()
        fakeFetch.mockReturnValue({ ok: true, json: () => Promise.resolve('["fake api"]') })
        window.fetch = fakeFetch
    })

    describe('events', () => {
        it('can build URL for events with properties', async () => {
            await api.events.list(
                {
                    properties: [
                        { key: 'something', value: 'is_set', operator: PropertyOperator.IsSet, type: 'event' },
                    ],
                },
                2
            )

            expect(fakeFetch).toHaveBeenCalledWith(
                '/api/projects/2/events?properties=%5B%7B%22key%22%3A%22something%22%2C%22value%22%3A%22is_set%22%2C%22operator%22%3A%22is_set%22%2C%22type%22%3A%22event%22%7D%5D',
                { signal: undefined }
            )
        })
    })

    describe('normalising URLs', () => {
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
                it(`when API is using verb ${verb} it normalises ${testCase.url} to ${testCase.expected}`, () => {
                    api[verb](testCase.url)
                    expect(fakeFetch.mock.calls[0][0]).toEqual(testCase.expected)
                })
            })
        })
    })
})
