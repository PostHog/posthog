import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { editMetricsTableWidgetModalLogic } from './editMetricsTableWidgetModalLogic'

const REQUESTS = { label: 'Requests/s', metricName: 'http_requests_total', aggregation: 'rate' as const }
const LATENCY = {
    label: 'p95',
    metricName: 'http_request_duration_seconds',
    aggregation: 'histogram_quantile' as const,
    quantile: 0.95,
}

describe('editMetricsTableWidgetModalLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    function mountLogic(config: Record<string, unknown>): {
        logic: ReturnType<typeof editMetricsTableWidgetModalLogic.build>
        onSave: jest.Mock
    } {
        const onSave = jest.fn().mockResolvedValue(undefined)
        const logic = editMetricsTableWidgetModalLogic({
            config,
            onSave,
            onClose: jest.fn(),
            defaultTitle: 'Metrics table',
        })
        logic.mount()
        return { logic, onSave }
    }

    it('saves the label and the columns that the user builds', async () => {
        const { logic, onSave } = mountLogic({})

        logic.actions.setGroupBy('http.route')
        logic.actions.addColumn()
        logic.actions.updateColumn(0, REQUESTS)
        logic.actions.setInterval('minute_5')
        await expectLogic(logic, () => logic.actions.submit()).toFinishAllListeners()

        expect(onSave).toHaveBeenCalledTimes(1)
        expect(onSave.mock.calls[0][0]).toMatchObject({
            groupBy: 'http.route',
            columns: [REQUESTS],
            interval: 'minute_5',
        })
    })

    it('blocks the save until every column has a metric', () => {
        const { logic } = mountLogic({ groupBy: 'http.route' })

        logic.actions.addColumn()
        expect(logic.values.saveDisabledReason).toEqual('Pick a metric for every column')

        logic.actions.updateColumn(0, { metricName: 'http_requests_total' })
        expect(logic.values.saveDisabledReason).toBeUndefined()
    })

    it.each([2.5, 0])('blocks the save for a row limit of %s', (limit) => {
        const { logic } = mountLogic({ groupBy: 'http.route', columns: [REQUESTS] })

        logic.actions.setLimit(limit)

        expect(logic.values.saveDisabledReason).toEqual('Enter a whole number of rows from 1 to 100')
    })

    it('adds a quantile only while the column reads a histogram', () => {
        const { logic } = mountLogic({ groupBy: 'http.route', columns: [REQUESTS] })

        logic.actions.updateColumn(0, { aggregation: 'histogram_quantile' })
        expect(logic.values.columns[0].quantile).toEqual(0.95)

        logic.actions.updateColumn(0, { aggregation: 'avg' })
        expect(logic.values.columns[0].quantile).toBeUndefined()
    })

    it('keeps the sort column in range when the user removes a column', () => {
        const { logic } = mountLogic({ groupBy: 'http.route', columns: [REQUESTS, LATENCY], orderByColumn: 1 })

        logic.actions.removeColumn(1)

        expect(logic.values.columns).toEqual([REQUESTS])
        expect(logic.values.orderByColumn).toEqual(0)
    })
})
