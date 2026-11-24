import { metricChartTableProps } from './metricChartTableProps'

describe('metricChartTableProps', () => {
    it('reloads each tab with its own chart only', () => {
        const [traces, users] = ['llm-analytics-traces', 'llm-analytics-users'].map((key) => {
            const { context } = metricChartTableProps(key, {})
            const chart = context.dataTableBelowToolbar as JSX.Element
            return { table: context.insightProps?.dataNodeCollectionId, chart: chart.props.collectionId }
        })

        expect(traces.chart).toBe(traces.table)
        expect(users.chart).toBe(users.table)
        expect(traces.table).not.toBe(users.table)
    })
})
