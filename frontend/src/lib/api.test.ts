import api from 'lib/api'

describe('API helper', () => {
    describe('getting URLs', () => {
        let fakeFetch: jest.Mock<any, any>

        beforeEach(() => {
            fakeFetch = jest.fn()
            window.fetch = fakeFetch
        })

        it('adds a leading slash to relative URLs', () => {
            api.get('relative/url')
            expect(fakeFetch.mock.calls[0][0]).toEqual('/relative/url/')
        })

        it('does not add leading slash when absolute url with no http', () => {
            api.get('/absolute/url')
            expect(fakeFetch.mock.calls[0][0]).toEqual('/absolute/url/')
        })

        it('does not add leading slash to http urls', () => {
            api.get('http://some/url')
            expect(fakeFetch.mock.calls[0][0]).toEqual('http://some/url')
        })

        it('does not add leading slash to https urls', () => {
            api.get('https://some/url')
            expect(fakeFetch.mock.calls[0][0]).toEqual('https://some/url')
        })
    })
})
