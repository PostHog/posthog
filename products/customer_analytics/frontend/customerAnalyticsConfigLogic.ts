import { actions, connect, kea, listeners, path, selectors } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { ActionsNode, CustomerAnalyticsConfig, DataWarehouseNode, EventsNode } from '~/queries/schema/schema-general'

import type { customerAnalyticsConfigLogicType } from './customerAnalyticsConfigLogicType'

export const customerAnalyticsConfigLogic = kea<customerAnalyticsConfigLogicType>([
    path(['products', 'customerAnalytics', 'customerAnalyticsConfigModel']),

    actions({
        loadConfig: true,
        updateEvents: (events: Record<string, ActionsNode | EventsNode | DataWarehouseNode>) => ({ events }),
    }),

    connect(() => ({
        values: [teamLogic, ['customerAnalyticsConfig']],
        actions: [teamLogic, ['updateCurrentTeam']],
    })),
    selectors({
        activityEvent: [
            (s) => [s.customerAnalyticsConfig],
            (config: CustomerAnalyticsConfig) => ({ ...config.activity_event, custom_name: 'Activity' }),
        ],
        signupEvent: [
            (s) => [s.customerAnalyticsConfig],
            (config: CustomerAnalyticsConfig) => ({ ...config.signup_event, custom_name: 'Signups' }),
        ],
        signupPageviewEvent: [
            (s) => [s.customerAnalyticsConfig],
            (config: CustomerAnalyticsConfig) => ({ ...config.signup_pageview_event, custom_name: 'Signup pageviews' }),
        ],
        subscriptionEvent: [
            (s) => [s.customerAnalyticsConfig],
            (config: CustomerAnalyticsConfig) => ({ ...config.subscription_event, custom_name: 'Subscriptions' }),
        ],
        paymentEvent: [
            (s) => [s.customerAnalyticsConfig],
            (config: CustomerAnalyticsConfig) => ({ ...config.payment_event, custom_name: 'Payments' }),
        ],
    }),

    listeners(({ actions }) => ({
        updateEvents: ({ events }) => {
            const customer_analytics_config = { ...events } as any as CustomerAnalyticsConfig
            actions.updateCurrentTeam({ customer_analytics_config })
        },
    })),
])
