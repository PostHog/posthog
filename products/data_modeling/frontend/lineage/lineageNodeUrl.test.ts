import { lineageNodeUrl } from './lineageNodeUrl'

describe('lineageNodeUrl', () => {
    it('sends a metric node to its catalog page, keyed by name', () => {
        expect(lineageNodeUrl({ id: 'node-1', name: 'weekly_active_accounts', type: 'metric' })).toEqual(
            '/data-catalog/metrics/weekly_active_accounts'
        )
    })

    it.each([
        ['lineage', 'lineage'],
        ['data-quality', 'data_quality'],
        ['materialization', 'configuration'],
    ] as const)('opens an endpoint version on its %s tab', (modelTab, endpointTab) => {
        const url = lineageNodeUrl(
            {
                id: 'node-1',
                name: 'internal_v1',
                type: 'endpoint',
                endpoint: { name: 'weekly_activity', version: 2, is_materialized: false },
            },
            modelTab
        )
        expect(url).toBe(`/endpoints/weekly_activity?version=2&tab=${endpointTab}`)
    })

    it('sends an endpoint without a version link to the endpoint list', () => {
        expect(lineageNodeUrl({ id: 'orphan', name: 'internal_v1', type: 'endpoint' })).toBe('/endpoints')
    })

    it.each(['table', 'view', 'matview'] as const)('sends a %s node to its node page', (type) => {
        expect(lineageNodeUrl({ id: 'node-1', name: 'orders', type }, 'lineage')).toEqual('/models/node-1/lineage')
    })
})
