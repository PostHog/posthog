import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'

import { isEmptyObject } from 'lib/utils'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { seriesToActionsAndEvents } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { ActionsNode, DataWarehouseNode, EventsNode, GroupNode } from '~/queries/schema/schema-general'
import { FilterType, InsightType } from '~/types'

import { customerAnalyticsConfigLogic } from 'products/customer_analytics/frontend/customerAnalyticsConfigLogic'

import { EventSelectorProps } from './CustomerAnalyticsDashboardEvents'
import type { customerAnalyticsDashboardEventsLogicType } from './customerAnalyticsDashboardEventsLogicType'

export const customerAnalyticsDashboardEventsLogic = kea<customerAnalyticsDashboardEventsLogicType>([
    path(['products', 'customerAnalytics', 'components', 'insights', 'eventConfigModal']),
    connect(() => ({
        values: [
            customerAnalyticsConfigLogic,
            ['activityEvent', 'signupEvent', 'signupPageviewEvent', 'subscriptionEvent', 'paymentEvent'],
        ],
        actions: [customerAnalyticsConfigLogic, ['updateEvents']],
    })),
    actions({
        addEventToHighlight: (event: string) => ({ event }),
        clearEventsToHighlight: true,
        clearFilterSelections: true,
        setActivityEventSelection: (filters: FilterType | null) => ({
            filters,
        }),
        setSignupEventSelection: (filters: FilterType | null) => ({
            filters,
        }),
        setSignupPageviewEventSelection: (filters: FilterType | null) => ({
            filters,
        }),
        setPaymentEventSelection: (filters: FilterType | null) => ({
            filters,
        }),
        setSubscriptionEventSelection: (filters: FilterType | null) => ({
            filters,
        }),
        saveEvents: true,
    }),
    reducers({
        activityEventSelection: [
            null as FilterType | null,
            {
                setActivityEventSelection: (_, { filters }) => filters,
                clearFilterSelections: () => null,
            },
        ],
        signupEventSelection: [
            null as FilterType | null,
            {
                setSignupEventSelection: (_, { filters }) => filters,
                clearFilterSelections: () => null,
            },
        ],
        signupPageviewEventSelection: [
            null as FilterType | null,
            {
                setSignupPageviewEventSelection: (_, { filters }) => filters,
                clearFilterSelections: () => null,
            },
        ],
        paymentEventSelection: [
            null as FilterType | null,
            {
                setPaymentEventSelection: (_, { filters }) => filters,
                clearFilterSelections: () => null,
            },
        ],
        subscriptionEventSelection: [
            null as FilterType | null,
            {
                setSubscriptionEventSelection: (_, { filters }) => filters,
                clearFilterSelections: () => null,
            },
        ],
        eventsToHighlight: [
            [] as string[],
            {
                addEventToHighlight: (state, { event }) => [...state, event],
                clearEventsToHighlight: () => [],
            },
        ],
    }),
    selectors(({ actions }) => ({
        activityEventFilters: [
            (s) => [s.activityEvent, s.activityEventSelection],
            (activityEvent, activityEventSelection): FilterType => {
                if (activityEventSelection) {
                    return activityEventSelection
                }
                return {
                    insight: InsightType.TRENDS,
                    ...seriesToActionsAndEvents(activityEvent ? [activityEvent] : []),
                }
            },
        ],
        signupEventFilters: [
            (s) => [s.signupEvent, s.signupEventSelection],
            (signupEvent, signupEventSelection): FilterType | null => {
                if (signupEventSelection) {
                    return signupEventSelection
                }
                if (isEmptyObject(signupEvent)) {
                    return null
                }
                return {
                    insight: InsightType.TRENDS,
                    ...seriesToActionsAndEvents([signupEvent]),
                }
            },
        ],
        signupPageviewEventFilters: [
            (s) => [s.signupPageviewEvent, s.signupPageviewEventSelection],
            (signupPageviewEvent, signupPageviewEventSelection): FilterType | null => {
                if (signupPageviewEventSelection) {
                    return signupPageviewEventSelection
                }
                if (isEmptyObject(signupPageviewEvent as object)) {
                    return null
                }
                return {
                    insight: InsightType.TRENDS,
                    ...seriesToActionsAndEvents([signupPageviewEvent]),
                }
            },
        ],
        paymentEventFilters: [
            (s) => [s.paymentEvent, s.paymentEventSelection],
            (paymentEvent, paymentEventSelection): FilterType | null => {
                if (paymentEventSelection) {
                    return paymentEventSelection
                }
                if (isEmptyObject(paymentEvent as object)) {
                    return null
                }
                return {
                    insight: InsightType.TRENDS,
                    ...seriesToActionsAndEvents([paymentEvent]),
                }
            },
        ],
        subscriptionEventFilters: [
            (s) => [s.subscriptionEvent, s.subscriptionEventSelection],
            (subscriptionEvent, subscriptionEventSelection): FilterType | null => {
                if (subscriptionEventSelection) {
                    return subscriptionEventSelection
                }
                if (isEmptyObject(subscriptionEvent as object)) {
                    return null
                }
                return {
                    insight: InsightType.TRENDS,
                    ...seriesToActionsAndEvents([subscriptionEvent]),
                }
            },
        ],
        hasChanges: [
            (s) => [
                s.activityEventSelection,
                s.signupEventSelection,
                s.signupPageviewEventSelection,
                s.paymentEventSelection,
                s.subscriptionEventSelection,
            ],
            (
                activityEventSelection,
                signupEventSelection,
                signupPageviewEventSelection,
                paymentEventSelection,
                subscriptionEventSelection
            ): boolean => {
                return (
                    activityEventSelection !== null ||
                    signupEventSelection !== null ||
                    signupPageviewEventSelection !== null ||
                    paymentEventSelection !== null ||
                    subscriptionEventSelection !== null
                )
            },
        ],
        activityEventSelector: [
            (s) => [s.activityEventFilters],
            (activityEventFilters): EventSelectorProps => ({
                title: 'Activity event',
                caption: 'Defines what is considered user activity for active users and engagement calculations',
                filters: activityEventFilters,
                setFilters: actions.setActivityEventSelection,
                prompt: 'What custom events or actions can be used to define active product usage?',
                relatedSeries: ['dauSeries', 'mauSeries', 'wauSeries'],
            }),
        ],
        signupPageviewEventSelector: [
            (s) => [s.signupPageviewEventFilters],
            (signupPageviewEventFilters): EventSelectorProps => ({
                title: 'Signup pageview event',
                caption: 'Tracks when users view the signup page. Used to calculate signup conversion',
                filters: signupPageviewEventFilters,
                setFilters: actions.setSignupPageviewEventSelection,
                prompt: 'What pageview pathnames can be used to define signup pageviews based on my events?',
                relatedSeries: ['signupPageviewSeries'],
            }),
        ],
        signupEventSelector: [
            (s) => [s.signupEventFilters],
            (signupEventFilters): EventSelectorProps => ({
                title: 'Signup event',
                caption: 'Tracks when users complete registration or account creation',
                filters: signupEventFilters,
                setFilters: actions.setSignupEventSelection,
                prompt: 'What events or actions can be used to define user signup?',
                relatedSeries: ['signupSeries'],
            }),
        ],
        subscriptionEventSelector: [
            (s) => [s.subscriptionEventFilters],
            (subscriptionEventFilters) => ({
                title: 'Subscription event',
                caption: 'Tracks when users subscribe to a plan. May or may not be associated with a payment',
                filters: subscriptionEventFilters,
                setFilters: actions.setSubscriptionEventSelection,
                prompt: 'What events or actions can be used to define user subscription?',
                relatedSeries: ['subscriptionSeries'],
            }),
        ],
        paymentEventSelector: [
            (s) => [s.paymentEventFilters],
            (paymentEventFilters) => ({
                title: 'Payment event',
                caption: 'Tracks when users complete a payment. Used to calculate free-to-paid conversion',
                filters: paymentEventFilters,
                setFilters: actions.setPaymentEventSelection,
                prompt: 'What events or actions can be used to define user payment?',
                relatedSeries: ['paymentSeries'],
            }),
        ],
        eventSelectors: [
            (s) => [
                s.activityEventSelector,
                s.signupPageviewEventSelector,
                s.signupEventSelector,
                s.subscriptionEventSelector,
                s.paymentEventSelector,
            ],
            (
                activityEventSelector,
                signupPageviewEventSelector,
                signupEventSelector,
                subscriptionEventSelector,
                paymentEventSelector
            ): EventSelectorProps[] => [
                activityEventSelector,
                signupPageviewEventSelector,
                signupEventSelector,
                subscriptionEventSelector,
                paymentEventSelector,
            ],
        ],
    })),
    listeners(({ actions, values }) => ({
        saveEvents: () => {
            const events: Record<string, ActionsNode | EventsNode | DataWarehouseNode | GroupNode> = {}
            if (values.activityEventSelection) {
                const activityEvents = actionsAndEventsToSeries(
                    values.activityEventSelection as any,
                    true,
                    MathAvailability.None
                )
                events['activity_event'] = activityEvents[0]
            }
            if (values.signupEventSelection) {
                const signupEvents = actionsAndEventsToSeries(
                    values.signupEventSelection as any,
                    true,
                    MathAvailability.None
                )
                events['signup_event'] = signupEvents[0]
            }
            if (values.signupPageviewEventSelection) {
                const signupPageviewEvents = actionsAndEventsToSeries(
                    values.signupPageviewEventSelection as any,
                    true,
                    MathAvailability.None
                )
                events['signup_pageview_event'] = signupPageviewEvents[0]
            }
            if (values.paymentEventSelection) {
                const paymentEvents = actionsAndEventsToSeries(
                    values.paymentEventSelection as any,
                    true,
                    MathAvailability.None
                )
                events['payment_event'] = paymentEvents[0]
            }
            if (values.subscriptionEventSelection) {
                const subscriptionEvents = actionsAndEventsToSeries(
                    values.subscriptionEventSelection as any,
                    true,
                    MathAvailability.None
                )
                events['subscription_event'] = subscriptionEvents[0]
            }
            actions.updateEvents(events)
        },
    })),

    urlToAction(({ actions }) => ({
        '*': () => {
            // Clear highlights when navigating away from configuration page
            if (!window.location.pathname.includes('/customer_analytics/configuration')) {
                actions.clearEventsToHighlight()
            }
        },
    })),
])
