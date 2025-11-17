import { actions, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { ActionsNode, EventsNode } from '~/queries/schema/schema-general'

import type { customerAnalyticsConfigModelType } from './customerAnalyticsConfigModelType'
import { CustomerAnalyticsConfigType } from './types'

export const customerAnalyticsConfigModel = kea<customerAnalyticsConfigModelType>([
    path(['products', 'customerAnalytics', 'customerAnalyticsConfigModel']),

    actions({
        loadConfig: true,
        updateActivityEvent: (activityEvent: EventsNode | ActionsNode) => ({ activityEvent }),
        updateConfig: (data: Partial<CustomerAnalyticsConfigType>) => ({ data }),
    }),

    loaders(({ values }) => ({
        config: [
            null as CustomerAnalyticsConfigType | null,
            {
                loadConfig: async () => {
                    return await api.customerAnalyticsConfig.get_or_create()
                },
                updateConfig: async ({ data }) => {
                    if (!values.config) {
                        throw new Error('No config to update')
                    }
                    return await api.customerAnalyticsConfig.update(data)
                },
            },
        ],
    })),

    selectors({
        activityEvent: [(s) => [s.config], (config: CustomerAnalyticsConfigType | null) => config?.activity_event],
    }),

    listeners(({ actions }) => ({
        updateActivityEvent: ({ activityEvent }) => {
            actions.updateConfig({ activity_event: activityEvent })
        },
    })),
])
