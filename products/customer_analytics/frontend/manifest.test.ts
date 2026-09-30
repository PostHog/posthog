import { manifest } from '../manifest'

describe('customer analytics manifest', () => {
    it('redirects the old announcements tab URL to shoutouts and keeps the query and hash', () => {
        const redirect = manifest.redirects?.['/customer_analytics/announcements']

        expect(typeof redirect).toBe('function')
        expect((redirect as (...args: any[]) => string)({}, { search: 'acme' }, { panel: 'x' })).toEqual(
            '/customer_analytics/shoutouts?search=acme#panel=x'
        )
    })
})
