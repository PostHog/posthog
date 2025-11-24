import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { isEmptyObject } from 'lib/utils'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { seriesToActionsAndEvents } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { ActionsNode, DataWarehouseNode, EventsNode } from '~/queries/schema/schema-general'
import { FilterType, InsightType } from '~/types'

import { customerAnalyticsConfigLogic } from 'products/customer_analytics/frontend/customerAnalyticsConfigLogic'

import { EventSelectorProps } from './EventConfigModal'
import type { eventConfigModalLogicType } from './eventConfigModalLogicType'

export const eventConfigModalLogic = kea<eventConfigModalLogicType>([
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
        toggleModalOpen: (isOpen?: boolean) => ({ isOpen }),
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
        isOpen: [
            false,
            {
                toggleModalOpen: (state, { isOpen }) => (isOpen !== undefined ? isOpen : !state),
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
                if (isEmptyObject(signupEvent as object)) {
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
        eventSelectors: [
            (s) => [
                s.activityEventFilters,
                s.signupEventFilters,
                s.signupPageviewEventFilters,
                s.paymentEventFilters,
                s.subscriptionEventFilters,
            ],
            (
                activityEventFilters,
                signupEventFilters,
                signupPageviewEventFilters,
                paymentEventFilters,
                subscriptionEventFilters
            ): EventSelectorProps[] => [
                {
                    title: 'Activity event',
                    caption: 'Defines what is considered user activity for active users and engagement calculations',
                    filters: activityEventFilters,
                    setFilters: actions.setActivityEventSelection,
                },
                {
                    title: 'Signup event',
                    caption: 'Tracks when users complete registration or account creation',
                    filters: signupEventFilters,
                    setFilters: actions.setSignupEventSelection,
                },
                {
                    title: 'Signup pageview event',
                    caption: 'Tracks when users view the signup page',
                    filters: signupPageviewEventFilters,
                    setFilters: actions.setSignupPageviewEventSelection,
                },
                {
                    title: 'Payment event',
                    caption: 'Tracks when users complete payment transactions',
                    filters: paymentEventFilters,
                    setFilters: actions.setPaymentEventSelection,
                },
                {
                    title: 'Subscription event',
                    caption: 'Tracks when users subscribe to a plan',
                    filters: subscriptionEventFilters,
                    setFilters: actions.setSubscriptionEventSelection,
                },
            ],
        ],
    })),
    listeners(({ actions, values }) => ({
        saveEvents: () => {
            const events: Record<string, ActionsNode | EventsNode | DataWarehouseNode> = {}
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
        toggleModalOpen: ({ isOpen }) => {
            const isClosing = isOpen === false || (isOpen === undefined && values.isOpen)
            if (isClosing) {
                actions.setActivityEventSelection(null)
                actions.setSignupEventSelection(null)
                actions.setSignupPageviewEventSelection(null)
                actions.setPaymentEventSelection(null)
                actions.setSubscriptionEventSelection(null)
            }
        },
    })),
])
