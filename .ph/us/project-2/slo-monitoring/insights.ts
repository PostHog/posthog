import { hogql, insight, type InsightDefinition, type InsightInput, trend } from '@posthog/sdk/define'

import { type SloOperation, tags } from './config'
import { burnRateQuery, durationQuery, regressionQuery, successRateQuery, volumeQuery } from './queries'

const plain = { formatting: { prefix: '', suffix: '' } }

// The generated chart settings type has no goal line `position` yet, and the dashboard's goal lines have one, so they are declared apart from the literal it checks.
const burnRateGoalLines = [
    { label: 'Budget rate', value: 0.3, position: 'start' },
    { label: '100x burn', value: 2, position: 'start' },
]

function regionSuffix(operation: SloOperation, region: string): string {
    return operation.regions.length > 1 ? ` — ${region}` : ''
}

// One per operation and region. The dashboard places them, so they have no key of their own here.
export function burnRate(operation: SloOperation, region: string): InsightInput {
    const ask = `Investigate+${operation.key}+failures+in+${region}+region.+Check+slo_operation_started+events+without+matching+slo_operation_completed+success+outcomes+in+the+last+24h`
    return hogql({
        name: `SLO: Burn Rates - ${operation.name} (${operation.slo}%)${regionSuffix(operation, region)}`,
        description: `[Investigate failures with AI](/ai?ask=${ask})`,
        tags,
        query: burnRateQuery(operation, region),
        display: 'ActionsLineGraph',
        chartSettings: {
            xAxis: { column: 'time' },
            yAxis: [{ column: 'value', settings: plain }],
            seriesBreakdownColumn: 'metric',
            showLegend: true,
            goalLines: burnRateGoalLines,
        },
        tableSettings: {
            columns: [
                { column: 'time', settings: plain },
                { column: 'metric', settings: plain },
                { column: 'value', settings: plain },
            ],
        },
    })
}

export function duration(operation: SloOperation, region: string): InsightInput {
    const seconds = { style: 'number' as const, prefix: '', suffix: 's' }
    return hogql({
        name: `SLO: Duration - ${operation.name}${regionSuffix(operation, region)}`,
        tags,
        query: durationQuery(operation, region),
        display: 'ActionsAreaGraph',
        chartSettings: {
            xAxis: { column: 'day' },
            yAxis: [
                {
                    column: 'value',
                    settings: {
                        display: {
                            color: '#1d4aff',
                            label: '',
                            trendLine: false,
                            displayType: 'auto',
                            yAxisPosition: 'left',
                        },
                        formatting: seconds,
                    },
                },
            ],
            seriesBreakdownColumn: 'metric',
        },
        tableSettings: {
            columns: [
                { column: 'day', settings: plain },
                { column: 'metric', settings: plain },
                { column: 'value', settings: { formatting: seconds } },
            ],
        },
    })
}

export const successRate = insight(
    'slo_success_rate',
    hogql({
        name: 'SLO: 28d Success Rate',
        tags,
        query: successRateQuery,
        display: 'ActionsLineGraph',
        chartSettings: {
            xAxis: { column: 'day' },
            yAxis: [{ column: 'success_rate', settings: { formatting: { prefix: '', suffix: '%' } } }],
            seriesBreakdownColumn: 'operation',
            showLegend: true,
        },
        tableSettings: {
            columns: [
                { column: 'day', settings: plain },
                { column: 'operation', settings: plain },
                { column: 'success_rate', settings: { formatting: { prefix: '', suffix: '%' } } },
            ],
        },
    })
)

export const volume = insight(
    'slo_volume',
    hogql({ name: 'SLO: 28d Volume by Operation', description: '* = all regions', tags, query: volumeQuery })
)

// Drives the regression alert, so it covers every operation and region that sends SLO events.
export const regression = insight(
    'slo_regression',
    hogql({
        name: 'SLO: Daily burn rate regression by operation',
        description:
            "Yesterday's burn rate (99.95% target) / median of the prior 14 days, floored at 1x. 0 when yesterday had <100 operations or <10 failures.",
        tags,
        query: regressionQuery,
        display: 'ActionsTable',
    })
)

function deliveryFailureRate(region: string): InsightDefinition {
    const delivery = [
        { key: 'operation', type: 'event', value: 'alert_delivery', operator: 'exact' },
        { key: 'region', type: 'event', value: region, operator: 'exact' },
    ] as const
    return insight(
        `alert_delivery_failure_rate_${region.toLowerCase()}`,
        trend({
            name: `SLO: Alert notification delivery failure rate (${region})`,
            description: 'Daily failed alert notification deliveries among completed attempts.',
            tags,
            interval: 'day',
            dateRange: { date_from: '-7d' },
            series: [
                {
                    event: 'slo_operation_completed',
                    math: 'total',
                    custom_name: 'Failed',
                    properties: [
                        ...delivery,
                        { key: 'outcome', type: 'event', value: 'failure', operator: 'exact' } as const,
                    ],
                },
                {
                    event: 'slo_operation_completed',
                    math: 'total',
                    custom_name: 'Completed',
                    properties: [...delivery],
                },
            ],
            trendsFilter: {
                display: 'ActionsLineGraph',
                formulaNodes: [{ formula: 'A/B', custom_name: 'Failure rate' }],
                aggregationAxisFormat: 'percentage_scaled',
                decimalPlaces: 4,
                showAlertThresholdLines: true,
            },
        })
    )
}

export const alertDeliveryFailureRate = { US: deliveryFailureRate('US'), EU: deliveryFailureRate('EU') }
