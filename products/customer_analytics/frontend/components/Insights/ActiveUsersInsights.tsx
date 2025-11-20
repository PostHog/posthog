import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import { isEventsNode } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { customerAnalyticsSceneLogic } from '../../customerAnalyticsSceneLogic'
import { InsightDefinition } from '../../insightDefinitions'
import { CustomerAnalyticsQueryCard } from '../CustomerAnalyticsQueryCard'
import { EventConfigModal } from './EventConfigModal'

export function ActiveUsersInsights(): JSX.Element {
    const { activityEvent, activeUsersInsights, tabId } = useValues(customerAnalyticsSceneLogic)
    const { toggleEventConfigModal } = useActions(customerAnalyticsSceneLogic)

    // Check if using pageview as default
    const isOnlyPageview = isEventsNode(activityEvent) && activityEvent.event === '$pageview'

    return (
        <div className="space-y-2 mb-0">
            {isOnlyPageview && (
                <LemonBanner type="warning">
                    You are currently using the pageview event to define user activity. Consider using a more specific
                    event or action to track activity accurately.
                    <div className="flex flex-row items-center gap-4 mt-2 max-w-160">
                        <LemonButton type="primary" onClick={() => toggleEventConfigModal()}>
                            Configure activity event
                        </LemonButton>
                    </div>
                </LemonBanner>
            )}
            <div className="flex items-center gap-2 ml-1">
                <h2 className="m-0">Active Users</h2>
                {!isOnlyPageview && (
                    <LemonButton
                        icon={<IconGear />}
                        size="small"
                        noPadding
                        onClick={() => toggleEventConfigModal()}
                        tooltip="Configure dashboard"
                    />
                )}
            </div>
            <div className="grid grid-cols-[3fr_1fr] gap-2">
                {activeUsersInsights.map((insight, index) => {
                    return (
                        <CustomerAnalyticsQueryCard key={index} insight={insight as InsightDefinition} tabId={tabId} />
                    )
                })}
            </div>
            <PowerUsersTable />
            <EventConfigModal />
        </div>
    )
}

function PowerUsersTable(): JSX.Element {
    const { dauSeries, tabId } = useValues(customerAnalyticsSceneLogic)

    const query = {
        kind: NodeKind.DataTableNode,
        hiddenColumns: ['id', 'person.$delete', 'event_distinct_ids'],
        showSourceQueryOptions: false,
        source: {
            kind: NodeKind.ActorsQuery,
            select: ['person', 'event_count'],
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
                },
                series: 0,
            },
            orderBy: ['event_count DESC'],
            limit: 10,
        },
    }

    return (
        <>
            <div className="flex items-center gap-2 ml-1">
                <h2 className="-mb-2">Power Users</h2>
                <LemonButton
                    size="small"
                    noPadding
                    targetBlank
                    to={urls.persons()}
                    tooltip="Open people list"
                    className="-mb-2"
                />
            </div>
            <Query
                uniqueKey={`power-users-${tabId}`}
                attachTo={customerAnalyticsSceneLogic}
                query={{ ...query, showTimings: false, showOpenEditorButton: false }}
                context={{
                    columns: {
                        event_count: { title: 'Event count' },
                    },
                }}
            />
        </>
    )
}
