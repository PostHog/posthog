import { lineageNodeUrl } from './lineageNodeUrl'

describe('lineageNodeUrl', () => {
    it('sends a metric node to its catalog page, keyed by name', () => {
        expect(lineageNodeUrl({ id: 'node-1', name: 'weekly_active_accounts', type: 'metric' })).toEqual(
            '/data-catalog/metrics/weekly_active_accounts'
        )
    })

    it('sends an insight node to the insight, keyed by short ID', () => {
        expect(
            lineageNodeUrl({ id: 'node-1', name: 'Weekly revenue', type: 'insight', insight_short_id: 'AbC123xY' })
        ).toEqual('/insights/AbC123xY')
    })

    it.each(['table', 'view', 'matview', 'endpoint'] as const)('sends a %s node to its node page', (type) => {
        expect(lineageNodeUrl({ id: 'node-1', name: 'orders', type }, 'lineage')).toEqual('/models/node-1/lineage')
    })
})
