import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    editMetricsTableWidgetModalLogic,
    metricsTableAggregationDisabledReason,
} from './editMetricsTableWidgetModalLogic'

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

    it.each(['histogram', 'exponential_histogram'])(
        'switches a column to a percentile when the user picks a %s metric',
        (type) => {
            const { logic } = mountLogic({ groupBy: 'http.route' })

            logic.actions.addColumn()
            logic.actions.selectColumnMetric(0, 'http_request_duration_seconds', type)

            expect(logic.values.columns[0]).toEqual({
                label: 'Value',
                metricName: 'http_request_duration_seconds',
                aggregation: 'histogram_quantile',
                quantile: 0.95,
            })
            expect(logic.values.columnMetricTypes).toEqual([type])
        }
    )

    it.each([
        ['sum', 'rate'],
        ['gauge', 'avg'],
    ])('switches a percentile column to a fitting calculation when the user picks a %s metric', (type, expected) => {
        const { logic } = mountLogic({ groupBy: 'http.route', columns: [LATENCY] })

        logic.actions.selectColumnMetric(0, 'other_metric', type)

        expect(logic.values.columns[0]).toEqual({ label: 'p95', metricName: 'other_metric', aggregation: expected })
    })

    it.each([
        ['sum', 'rate'],
        ['gauge', 'avg'],
    ])('gives a new column a fitting calculation when the user picks a %s metric', (type, expected) => {
        const { logic } = mountLogic({ groupBy: 'http.route' })

        logic.actions.addColumn()
        logic.actions.selectColumnMetric(0, 'some_metric', type)

        expect(logic.values.columns[0]).toEqual({ label: 'Value', metricName: 'some_metric', aggregation: expected })
    })

    it('keeps an average the user chose when they pick a sum metric for the column again', () => {
        const queue = { label: 'Queue size', metricName: 'queue_size', aggregation: 'avg' as const }
        const { logic } = mountLogic({ groupBy: 'queue', columns: [queue] })

        logic.actions.selectColumnMetric(0, 'queue_size', 'sum')

        expect(logic.values.columns[0]).toEqual(queue)
    })

    it('keeps the calculation when the picked metric has no known type', () => {
        const { logic } = mountLogic({ groupBy: 'http.route', columns: [LATENCY] })

        logic.actions.selectColumnMetric(0, 'metric_from_last_week')

        expect(logic.values.columns[0]).toEqual({ ...LATENCY, metricName: 'metric_from_last_week' })
        expect(logic.values.columnMetricTypes).toEqual([null])
    })

    it('keeps each metric type with its column when a column is removed', () => {
        const { logic } = mountLogic({ groupBy: 'http.route', columns: [REQUESTS, LATENCY] })

        expect(logic.values.columnMetricTypes).toEqual([null, null])
        logic.actions.selectColumnMetric(0, REQUESTS.metricName, 'sum')
        logic.actions.selectColumnMetric(1, LATENCY.metricName, 'histogram')
        logic.actions.removeColumn(0)
        logic.actions.addColumn()

        expect(logic.values.columnMetricTypes).toEqual(['histogram', null])
    })

    it.each([
        ['histogram', 'avg', true],
        ['histogram', 'rate', true],
        ['histogram', 'histogram_quantile', false],
        ['exponential_histogram', 'avg', true],
        ['exponential_histogram', 'histogram_quantile', false],
        ['sum', 'histogram_quantile', true],
        ['gauge', 'histogram_quantile', true],
        ['sum', 'rate', false],
        ['gauge', 'avg', false],
        [null, 'avg', false],
        [null, 'histogram_quantile', false],
    ] as const)('for a %s metric, the %s calculation is disabled: %s', (type, aggregation, disabled) => {
        expect(Boolean(metricsTableAggregationDisabledReason(type, aggregation))).toBe(disabled)
    })
})
