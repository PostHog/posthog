import { insight, type InsightDefinition } from '@posthog/sdk/define'

import { tags } from '../shared/teams'

type Region = 'US' | 'EU'

const property = (key: string, value: string): { key: string; type: 'event'; value: string[]; operator: 'exact' } => ({
    key,
    type: 'event',
    value: [value],
    operator: 'exact',
})

function deliveryRate(region: Region): InsightDefinition {
    return insight(`subscription_delivery_success_rate_${region.toLowerCase()}`, {
        name: `Subscription delivery success rate (${region})`,
        tags: [tags.managed],
        query: {
            kind: 'InsightVizNode',
            source: {
                kind: 'TrendsQuery',
                series: [
                    {
                        kind: 'EventsNode',
                        math: 'total',
                        event: 'slo_operation_started',
                        custom_name: 'Started',
                        properties: [property('operation', 'subscription_delivery'), property('region', region)],
                    },
                    {
                        kind: 'EventsNode',
                        math: 'total',
                        event: 'slo_operation_completed',
                        custom_name: 'Succeeded',
                        properties: [
                            property('operation', 'subscription_delivery'),
                            property('outcome', 'success'),
                            property('region', region),
                        ],
                    },
                ],
                version: 2,
                interval: 'day',
                dateRange: { date_from: '-30d' },
                trendsFilter: {
                    display: 'ActionsLineGraph',
                    showLegend: true,
                    showValuesOnSeries: true,
                    formulaNodes: [{ formula: 'B/A', custom_name: 'Success rate' }],
                    aggregationAxisFormat: 'percentage_scaled',
                },
                filterTestAccounts: false,
            },
        },
    })
}

export const subscriptionDelivery = { US: deliveryRate('US'), EU: deliveryRate('EU') }
