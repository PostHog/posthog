import { redactMetricVariableUrl, redactMetricVariableUrls } from './metricVariableUrlRedaction'

const filters = encodeURIComponent(
    JSON.stringify({ metricVariables: [{ name: 'env', query: "SELECT 'private_value'", current: { values: ['a'] } }] })
)

describe('redactMetricVariableUrl', () => {
    it.each([
        [
            'an insight link',
            `https://us.posthog.com/insights/abc?filters_override=${filters}#x`,
            'https://us.posthog.com/insights/abc',
        ],
        [
            'a dashboard',
            `https://us.posthog.com/dashboard/1?query_filters=${filters}`,
            'https://us.posthog.com/dashboard/1',
        ],
        [
            'a login redirect',
            `https://us.posthog.com/login?next=${encodeURIComponent(`/dashboard/1?query_filters=${filters}`)}`,
            'https://us.posthog.com/login',
        ],
        ['a relative link', `/insights/abc?filters_override=${filters}`, '/insights/abc'],
        ['an element chain', `a:attr__href="/insights/abc?filters_override=${filters}"`, ''],
    ])('keeps only the path of %s', (_name, text, expected) => {
        expect(redactMetricVariableUrl(text)).toBe(expected)
    })

    it('redacts every property of an event', () => {
        const url = `https://us.posthog.com/dashboard/1?query_filters=${filters}`

        const event = redactMetricVariableUrls({
            event: '$pageview',
            properties: {
                $current_url: url,
                $session_entry_url: url,
                $elements: [{ tag_name: 'a', attr__href: url.replace('https://us.posthog.com', '') }],
                $elements_chain: `a:attr__href="${url}"`,
            },
        } as any)

        expect(JSON.stringify(event)).not.toContain('private_value')
    })

    it('leaves a URL without metric variables as it is', () => {
        const url = 'https://us.posthog.com/dashboard/1?query_filters=%7B%22date_from%22%3A%22-7d%22%7D'

        expect(redactMetricVariableUrl(url)).toBe(url)
    })
})
