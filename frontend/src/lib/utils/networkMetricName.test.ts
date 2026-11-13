import { networkMetricName } from './networkMetricName'

describe('networkMetricName', () => {
    const originalLocation = window.location

    beforeEach(() => {
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: new URL('https://us.posthog.com/project/1'),
        })
    })

    afterEach(() => {
        Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
    })

    it.each(['https://live.us.posthog.com/notifications', 'https://live.us.posthog.com/events?teamId=2'])(
        'skips the livestream request %s',
        (url) => {
            expect(networkMetricName({ url })).toBeNull()
        }
    )

    it.each([
        'https://us.posthog.com/api/projects/1/notifications/',
        'https://live.us.posthog.com.example.com/notifications',
    ])('names every other request, such as %s', (url) => {
        expect(networkMetricName({ url })).toBe('http.client.request.duration')
    })
})
