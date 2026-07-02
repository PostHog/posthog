import { dropBrowserInjectedNoise } from './loadPostHogJS'

describe('dropBrowserInjectedNoise', () => {
    it('drops the Firefox iOS reader-mode injection error', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [
                    {
                        type: 'TypeError',
                        value: "undefined is not an object (evaluating 'window.__firefox__.reader')",
                    },
                ],
            },
        }
        expect(dropBrowserInjectedNoise(event)).toBeNull()
    })

    it.each([
        ['non-exception events', { event: '$pageview', properties: { $current_url: '/foo' } }],
        [
            'unrelated $exception events',
            {
                event: '$exception',
                properties: { $exception_list: [{ type: 'TypeError', value: 'x is not a function' }] },
            },
        ],
        ['$exception events with no list', { event: '$exception' }],
        ['$exception events with empty properties', { event: '$exception', properties: {} }],
    ])('passes %s through unchanged', (_label, event) => {
        expect(dropBrowserInjectedNoise(event)).toBe(event)
    })

    it('returns null when handed null (matching posthog-js before_send contract)', () => {
        expect(dropBrowserInjectedNoise(null)).toBeNull()
    })
})
