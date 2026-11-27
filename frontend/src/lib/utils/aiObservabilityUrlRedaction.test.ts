import type { CaptureResult } from 'posthog-js'

import { redactAIObservabilityUrls } from './aiObservabilityUrlRedaction'

const SECRET = 'jane@example.com sk-test-not-a-key'

describe('redactAIObservabilityUrls', () => {
    it('keeps customer text out of every URL an event carries', () => {
        const text = encodeURIComponent(SECRET)
        const page = `https://us.posthog.com/project/1/ai-observability/traces?date_from=-7d&error=${text}&tool=${text}&failed_tool=${text}&trace_search=${text}`
        const errors = `/project/1/ai-observability/errors?error_search=${text}&error=${text}`
        const tools = `/project/1/ai-observability/tools?tool_search=${text}#tool=${text}`
        const request = `https://us.posthog.com/api/projects/1/ai_observability/errors/?search=${text}&limit=50`
        const login = `https://us.posthog.com/login?next=${encodeURIComponent(page)}`

        const event = redactAIObservabilityUrls({
            uuid: 'event',
            event: 'llma traces list loaded',
            properties: {
                $current_url: page,
                $referrer: login,
                $elements_chain: `a:attr__href="${errors}";text="View"`,
                $elements: [{ tag_name: 'a', attr__href: tools }],
                $snapshot_data: [
                    { type: 6, data: { plugin: 'rrweb/network@1', payload: { requests: [{ name: request }] } } },
                ],
            },
            $set_once: { $initial_current_url: page },
        })

        const captured = JSON.stringify(event)
        expect(captured).not.toContain(text)
        expect(captured).not.toContain(encodeURIComponent(text))
        expect(event?.properties.$current_url).toBe(
            'https://us.posthog.com/project/1/ai-observability/traces?date_from=-7d&error=redacted&tool=redacted&failed_tool=redacted&trace_search=redacted'
        )
    })

    it('leaves the same parameters of other products alone', () => {
        const event: CaptureResult = {
            uuid: 'event',
            event: '$pageview',
            properties: { $current_url: '/oauth/callback?error=access_denied' },
        }

        expect(redactAIObservabilityUrls(event)).toEqual(event)
    })
})
