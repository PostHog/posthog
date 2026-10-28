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
        ['a BI selection', '/dashboard/1#bi_filter=%7B%22country%22%3A%22US%22%7D', '/dashboard/1'],
        ['a BI redirect', '/login?next=%2Fdashboard%2F1%23bi_filter%3Dvalue', '/login'],
        ['an autocaptured BI link', 'a:attr__href="/dashboard/1#bi_filter=value"', ''],
        ['a relative link', `/insights/abc?filters_override=${filters}`, '/insights/abc'],
        ['an element chain', `a:attr__href="/insights/abc?filters_override=${filters}"`, ''],
    ])('keeps only the path of %s', (_name, text, expected) => {
        expect(redactMetricVariableUrl(text)).toBe(expected)
    })

    it.each([
        `https://us.posthog.com/dashboard/1?query_filters=${filters}`,
        `https://us.posthog.com/dashboard/1#bi_filter=${encodeURIComponent(JSON.stringify({ record: { country: 'private_value' } }))}`,
    ])('redacts every property of an event containing %s', (url) => {
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

    it('redacts a URL deep inside a replay snapshot', () => {
        const href = `/insights/abc?filters_override=${filters}`
        const link = { type: 2, tagName: 'a', attributes: { href }, childNodes: [] }
        const page = { type: 0, childNodes: [{ type: 2, childNodes: [{ type: 2, childNodes: [link] }] }] }
        const snapshot = { type: 2, data: { node: page } }

        const event = redactMetricVariableUrls({
            event: '$snapshot',
            properties: { $snapshot_data: [snapshot] },
        } as any)

        expect(JSON.stringify(event)).not.toContain('private_value')
        expect(
            event!.properties.$snapshot_data[0].data.node.childNodes[0].childNodes[0].childNodes[0].attributes.href
        ).toBe('/insights/abc')
    })

    it('leaves an event without metric variables as the same objects', () => {
        const properties = { $snapshot_data: [{ data: { payload: { requests: [{ name: '/api/x' }] } } }] }

        expect(redactMetricVariableUrls({ event: '$snapshot', properties } as any)!.properties).toBe(properties)
    })

    it('leaves the requests that carry metric variable data out of a replay snapshot', () => {
        const kept = { name: '/api/environments/1/insights/', requestBody: '{"name":"Signups"}' }
        const requests = [
            kept,
            { name: `/api/environments/1/insights/?filters_override=${filters}` },
            { name: '/api/environments/1/metrics/variable_options/', requestBody: '{"query":"SELECT 1"}' },
            { name: '/api/dashboards/1', requestBody: JSON.stringify({ filters: { metricVariables: [] } }) },
        ]
        const snapshot = { type: 6, data: { plugin: 'rrweb/network@1', payload: { requests } } }

        const event = redactMetricVariableUrls({
            event: '$snapshot',
            properties: { $snapshot_data: [snapshot] },
        } as any)

        expect(event!.properties.$snapshot_data[0].data.payload.requests).toEqual([kept])
    })

    it('leaves a URL without metric variables as it is', () => {
        const url = 'https://us.posthog.com/dashboard/1?query_filters=%7B%22date_from%22%3A%22-7d%22%7D'

        expect(redactMetricVariableUrl(url)).toBe(url)
    })
})
