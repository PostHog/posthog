import { useValues } from 'kea'

import { LemonBanner, LemonButton, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, InsightLogicProps } from '~/types'

import { revenueAnalyticsLogic } from 'products/revenue_analytics/frontend/revenueAnalyticsLogic'

import { CUSTOMER_ANALYTICS_DATA_COLLECTION_NODE_ID } from '../../constants'
import { InsightDefinition, customerAnalyticsSceneLogic } from '../../customerAnalyticsSceneLogic'
import { buildDashboardItemId, isPageviewWithoutFilters } from '../../utils'
import { CustomerAnalyticsQueryCard } from '../CustomerAnalyticsQueryCard'

export function ActiveUsersInsights(): JSX.Element {
    const { activityEvent, activeUsersInsights, customerLabel, tabId } = useValues(customerAnalyticsSceneLogic)

    // Check if using pageview as default, with no properties filter
    const isOnlyPageview = isPageviewWithoutFilters(activityEvent)

    return (
        <div className="space-y-2">
            {isOnlyPageview && (
                <LemonBanner type="warning">
                    What makes a user active in your product? Choose an event that signals real engagement, like
                    completing a core action, rather than generic pageviews.
                    <div className="flex flex-row items-center gap-4 mt-2 max-w-160">
                        <LemonButton
                            data-attr="customer-analytics-configure-activity-event"
                            to={urls.customerAnalyticsConfiguration()}
                            type="primary"
                        >
                            Configure activity event
                        </LemonButton>
                    </div>
                </LemonBanner>
            )}
            <h2 className="ml-1">Active {customerLabel.plural}</h2>
            <div className="grid grid-cols-[3fr_1fr] gap-2">
                {activeUsersInsights.map((insight, index) => {
                    return (
                        <CustomerAnalyticsQueryCard key={index} insight={insight as InsightDefinition} tabId={tabId} />
                    )
                })}
            </div>
            <PowerUsersTable />
        </div>
    )
}

function PowerUsersTable(): JSX.Element {
    const { businessType, customerLabel, dauSeries, selectedGroupType, tabId } = useValues(customerAnalyticsSceneLogic)
    const { isRevenueAnalyticsEnabled, baseCurrency } = useValues(revenueAnalyticsLogic)
    const uniqueKey = `power-users-${tabId}`
    const insightProps: InsightLogicProps<InsightVizNode> = {
        dataNodeCollectionId: CUSTOMER_ANALYTICS_DATA_COLLECTION_NODE_ID,
        dashboardItemId: buildDashboardItemId(uniqueKey),
    }

    const isB2c = businessType === 'b2c'
    const buttonTo = isB2c ? urls.persons() : urls.groups(selectedGroupType)
    const tooltip = isB2c ? 'Open people list' : `Open ${customerLabel.plural} list`
    const revenueFields = isRevenueAnalyticsEnabled ? ['$virt_mrr', '$virt_revenue'] : []

    const query = {
        kind: NodeKind.DataTableNode,
        hiddenColumns: ['id', 'person.$delete', 'event_distinct_ids'],
        showSourceQueryOptions: false,
        source: {
            kind: NodeKind.ActorsQuery,
            select: isB2c
                ? ['person_display_name -- Person', 'event_count', ...revenueFields, 'last_seen']
                : ['group', 'event_count', ...revenueFields, 'last_seen'],
            source: {
                kind: NodeKind.InsightActorsQuery,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [dauSeries],
                    dateRange: {
                        date_from: '-30d',
                    },
                    interval: 'day',
                    trendsFilter: {
                        display: ChartDisplayType.ActionsTable,
                    },
                    ...(isB2c ? {} : { aggregation_group_type_index: selectedGroupType }),
                },
                series: 0,
            },
            orderBy: ['event_count DESC'],
            limit: 10,
        },
    }

    return (
        <>
            <div className="flex items-center gap-2">
                <Tooltip
                    title={`Power ${customerLabel.plural} are the ${customerLabel.plural} that performed your activity event most frequently in the past 30 days.`}
                    docLink="https://posthog.com/docs/customer-analytics/dashboard-metrics#power-users"
                >
                    <h2 className="mb-0 ml-1">Power {customerLabel.plural}</h2>
                </Tooltip>
                <LemonButton size="small" noPadding targetBlank to={buttonTo} tooltip={tooltip} />
            </div>
            <Query
                uniqueKey={uniqueKey}
                attachTo={customerAnalyticsSceneLogic}
                query={{ ...query, showTimings: false, showOpenEditorButton: false }}
                context={{
                    columns: {
                        event_count: { title: 'Event count' },
                        group: { title: customerLabel.singular },
                    },
                    insightProps,
                    baseCurrency,
                }}
            />
        </>
    )
}
