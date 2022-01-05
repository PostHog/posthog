import api from 'lib/api'

describe('API helper', () => {
    let fakeFetch: jest.Mock<any, any>

    const FAKE_FETCH_RESULT = ['fake API result']

    beforeEach(() => {
        fakeFetch = jest.fn()
        fakeFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(FAKE_FETCH_RESULT) })
        window.fetch = fakeFetch
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
})
