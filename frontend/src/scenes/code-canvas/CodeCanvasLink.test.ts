import { canvasDeepLink } from './CodeCanvasLink'

describe('canvasDeepLink', () => {
    it.each([
        ['a plain canvas link', {}, 'posthog-code://canvas/chan%2F1/dash%202'],
        ['a link to a copy', { fork: '1' }, 'posthog-code://canvas/chan%2F1/dash%202?fork=1'],
        ['an unrelated query param', { comment: 'c1' }, 'posthog-code://canvas/chan%2F1/dash%202'],
    ])('forwards %s to PostHog Desktop', (_label, searchParams, expected) => {
        expect(canvasDeepLink('chan/1', 'dash 2', searchParams)).toBe(expected)
    })
})
