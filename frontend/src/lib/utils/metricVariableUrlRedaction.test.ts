import {
    redactMetricVariableRequest,
    redactMetricVariableUrl,
    redactMetricVariableUrls,
} from './metricVariableUrlRedaction'

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

    it('redacts a request URL deep inside a replay snapshot', () => {
        const url = `https://us.posthog.com/api/environments/1/insights/?filters_override=${filters}`
        const request = { name: url, entryType: 'resource', initiatorType: 'fetch' }
        const snapshot = { type: 6, data: { plugin: 'rrweb/network@1', payload: { requests: [request] } } }

        const event = redactMetricVariableUrls({
            event: '$snapshot',
            properties: { $snapshot_data: [snapshot], $session_id: 's' },
        } as any)

        expect(JSON.stringify(event)).not.toContain('private_value')
        expect(event!.properties.$snapshot_data[0].data.payload.requests[0].name).toBe(
            'https://us.posthog.com/api/environments/1/insights/'
        )
    })

    it('leaves an event without metric variables as the same objects', () => {
        const properties = { $snapshot_data: [{ data: { payload: { requests: [{ name: '/api/x' }] } } }] }

        expect(redactMetricVariableUrls({ event: '$snapshot', properties } as any)!.properties).toBe(properties)
    })

    it.each([
        ['a tile refresh URL', { name: `/api/insights/?filters_override=${filters}` }, { name: '/api/insights/' }],
        [
            'a dashboard save body',
            { name: '/api/dashboards/1', requestBody: JSON.stringify({ filters: { metricVariables: [] } }) },
            { name: '/api/dashboards/1', requestBody: null },
        ],
        [
            'an options request',
            {
                name: '/api/environments/1/metrics/variable_options/',
                requestBody: '{"query":"x"}',
                responseBody: '{"results":["a"]}',
            },
            { name: '/api/environments/1/metrics/variable_options/', requestBody: null, responseBody: null },
        ],
    ])('masks %s in replay network capture', (_name, request, expected) => {
        expect(redactMetricVariableRequest(request as any)).toEqual(expect.objectContaining(expected))
    })

    it('leaves a URL without metric variables as it is', () => {
        const url = 'https://us.posthog.com/dashboard/1?query_filters=%7B%22date_from%22%3A%22-7d%22%7D'

        expect(redactMetricVariableUrl(url)).toBe(url)
    })
})
