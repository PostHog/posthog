import { kea } from 'kea'
import api from 'lib/api'
import { webAnalyticsLogic } from './webAnalyticsLogic'
import { createPathnamePropertyFilters } from './pageReportsLogic'
import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { PropertyOperator } from '~/types'

import type { pageEventsTableLogicType } from './pageEventsTableLogicType'

export interface PageEventsTableLogicProps {
    pageUrl: string
}

interface PageEvent {
    uuid: string
    event: string
    distinct_id: string
    timestamp: string
    properties: Record<string, any>
}

export const pageEventsTableLogic = kea<pageEventsTableLogicType>({
    path: (key) => ['scenes', 'web-analytics', 'pageEventsTableLogic', key],
    props: {} as PageEventsTableLogicProps,
    key: ({ pageUrl }) => pageUrl,

    connect: {
        values: [webAnalyticsLogic, ['dateFilter', 'shouldFilterTestAccounts']],
    },

    loaders: ({ props, values }) => ({
        events: [
            [] as PageEvent[],
            {
                loadEvents: async () => {
                    if (!props.pageUrl) {
                        return []
                    }

                    try {
                        // Create pathname + host filters from the URL
                        const propertyFilters = createPathnamePropertyFilters(props.pageUrl, true) // Always strip query params for event filtering

                        const query: EventsQuery = setLatestVersionsOnQuery({
                            kind: NodeKind.EventsQuery,
                            select: ['uuid', 'event', 'distinct_id', 'timestamp', 'properties'],
                            where: [
                                // Page URL filters (pathname + host)
                                ...propertyFilters.map((filter) => ({
                                    key: filter.key,
                                    value: filter.value,
                                    operator: filter.operator,
                                    type: filter.type,
                                })),
                                // Exclude pageview/pageleave events to focus on user interactions
                                {
                                    key: 'event',
                                    value: ['$pageview', '$pageleave'],
                                    operator: PropertyOperator.IsNot,
                                    type: 'event_metadata' as any,
                                },
                            ],
                            properties: [],
                            orderBy: ['timestamp DESC'],
                            limit: 100,
                            dateRange: {
                                date_from: values.dateFilter.dateFrom,
                                date_to: values.dateFilter.dateTo,
                            },
                            filterTestAccounts: values.shouldFilterTestAccounts,
                        })

                        const response = await api.query(query)

                        // Transform the response to match our interface
                        return (response.results || []).map((row: any) => ({
                            uuid: row[0],
                            event: row[1],
                            distinct_id: row[2],
                            timestamp: row[3],
                            properties: row[4] || {},
                        }))
                    } catch (error) {
                        console.error('Error loading page events:', error)
                        return []
                    }
                },
            },
        ],
    }),

    listeners: () => ({
        loadEvents: () => {
            // Automatically reload when the component mounts
        },
    }),

    afterMount: ({ actions }) => {
        actions.loadEvents()
    },
})
