import { actions, connect, kea, listeners, path, selectors } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { ActionsNode, CustomerAnalyticsConfig, EventsNode } from '~/queries/schema/schema-general'

import type { customerAnalyticsConfigLogicType } from './customerAnalyticsConfigLogicType'

export const customerAnalyticsConfigLogic = kea<customerAnalyticsConfigLogicType>([
    path(['products', 'customerAnalytics', 'customerAnalyticsConfigModel']),

    actions({
        loadConfig: true,
        updateActivityEvent: (activityEvent: EventsNode | ActionsNode) => ({ activityEvent }),
    }),

    connect(() => ({
        values: [teamLogic, ['customerAnalyticsConfig']],
        actions: [teamLogic, ['updateCurrentTeam']],
    })),
    selectors({
        activityEvent: [(s) => [s.customerAnalyticsConfig], (config: CustomerAnalyticsConfig) => config.activity_event],
        signupEvent: [(s) => [s.customerAnalyticsConfig], (config: CustomerAnalyticsConfig) => config.signup_event],
        signupPageviewEvent: [
            (s) => [s.customerAnalyticsConfig],
            (config: CustomerAnalyticsConfig) => config.signup_pageview_event,
        ],
        subscriptionEvent: [
            (s) => [s.customerAnalyticsConfig],
            (config: CustomerAnalyticsConfig) => config.subscription_event,
        ],
        paymentEvent: [(s) => [s.customerAnalyticsConfig], (config: CustomerAnalyticsConfig) => config.payment_event],
    }),

    listeners(({ actions }) => ({
        updateActivityEvent: ({ activityEvent }) => {
            const customer_analytics_config = { activity_event: activityEvent } as CustomerAnalyticsConfig
            actions.updateCurrentTeam({ customer_analytics_config })
        },
    })),
])
