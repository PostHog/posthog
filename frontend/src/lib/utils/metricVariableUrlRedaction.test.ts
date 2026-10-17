import { redactMetricVariableUrl, redactMetricVariableUrls } from './metricVariableUrlRedaction'

describe('redactMetricVariableUrl', () => {
    it.each([
        ['filters_override', '/insights/abc'],
        ['query_filters', '/dashboard/1'],
    ])('keeps only the names of metric variables in %s', (param, path) => {
        const filters = {
            date_from: '-7d',
            metricVariables: [
                { name: 'env', source: 'sql', query: 'SELECT private_value', current: { values: ['a'] } },
            ],
        }
        const url = `https://us.posthog.com${path}?${param}=${encodeURIComponent(JSON.stringify(filters))}`

        const redacted = new URL(redactMetricVariableUrl(url))

        expect(JSON.parse(redacted.searchParams.get(param)!)).toEqual({
            date_from: '-7d',
            metricVariables: [{ name: 'env' }],
        })
    })

    it('redacts every URL property of an event', () => {
        const filters = { metricVariables: [{ name: 'env', query: 'SELECT private_value' }] }
        const url = `https://us.posthog.com/dashboard/1?query_filters=${encodeURIComponent(JSON.stringify(filters))}`

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
