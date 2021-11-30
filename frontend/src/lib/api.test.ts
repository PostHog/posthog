import api from 'lib/api'

describe('API helper', () => {
    describe('getting URLs', () => {
        let fakeFetch: jest.Mock<any, any>

        beforeEach(() => {
            fakeFetch = jest.fn()
            fakeFetch.mockReturnValue({ ok: true, json: () => Promise.resolve('["fake api"]') })
            window.fetch = fakeFetch
        })

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
