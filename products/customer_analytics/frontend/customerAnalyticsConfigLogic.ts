import { actions, connect, kea, listeners, path, selectors } from 'kea'

import { isEmptyObject } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import {
    ActionsNode,
    AnyEntityNode,
    CustomerAnalyticsConfig,
    DataWarehouseNode,
    EventsNode,
    GroupNode,
} from '~/queries/schema/schema-general'

import type { customerAnalyticsConfigLogicType } from './customerAnalyticsConfigLogicType'

export const customerAnalyticsConfigLogic = kea<customerAnalyticsConfigLogicType>([
    path(['products', 'customerAnalytics', 'customerAnalyticsConfigModel']),

    actions({
        loadConfig: true,
        updateEvents: (events: Record<string, ActionsNode | EventsNode | DataWarehouseNode | GroupNode>) => ({
            events,
        }),
    }),

    connect(() => ({
        values: [teamLogic, ['customerAnalyticsConfig']],
        actions: [teamLogic, ['updateCurrentTeam']],
    })),
    selectors({
        activityEvent: [
            (s) => [s.customerAnalyticsConfig],
            (config: CustomerAnalyticsConfig): AnyEntityNode =>
                !isEmptyObject(config.activity_event)
                    ? { ...config.activity_event, custom_name: 'Activity' }
                    : ({} as AnyEntityNode),
        ],
        signupEvent: [
            (s) => [s.customerAnalyticsConfig],
            (config: CustomerAnalyticsConfig): AnyEntityNode =>
                !isEmptyObject(config.signup_event)
                    ? { ...config.signup_event, custom_name: 'Signups' }
                    : ({} as AnyEntityNode),
        ],
        signupPageviewEvent: [
            (s) => [s.customerAnalyticsConfig],
            (config: CustomerAnalyticsConfig): AnyEntityNode =>
                !isEmptyObject(config.signup_pageview_event)
                    ? { ...config.signup_pageview_event, custom_name: 'Signup pageviews' }
                    : ({} as AnyEntityNode),
        ],
        subscriptionEvent: [
            (s) => [s.customerAnalyticsConfig],
            (config: CustomerAnalyticsConfig): AnyEntityNode =>
                !isEmptyObject(config.subscription_event)
                    ? { ...config.subscription_event, custom_name: 'Subscriptions' }
                    : ({} as AnyEntityNode),
        ],
        paymentEvent: [
            (s) => [s.customerAnalyticsConfig],
            (config: CustomerAnalyticsConfig): AnyEntityNode =>
                !isEmptyObject(config.payment_event)
                    ? { ...config.payment_event, custom_name: 'Payments' }
                    : ({} as AnyEntityNode),
        ],
    }),

    listeners(({ actions }) => ({
        updateEvents: ({ events }) => {
            const customer_analytics_config = { ...events } as any as CustomerAnalyticsConfig
            actions.updateCurrentTeam({ customer_analytics_config })
        },
    })),
])
