import { isHttpsUrl } from './billingAlertNotificationLogic'

describe('billing alert notification input validation', () => {
    it('keeps browser validation to HTTPS completeness and leaves destination policy to the server', () => {
        expect(isHttpsUrl('https://example.com/webhook')).toBe(true)
        expect(isHttpsUrl('https://example.com:444/webhook')).toBe(true)
        expect(isHttpsUrl('http://example.com/webhook')).toBe(false)
        expect(isHttpsUrl('not a URL')).toBe(false)
    })
})
