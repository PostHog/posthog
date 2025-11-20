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
        hasChanges: [
            (s) => [s.activityEventSelection, s.signupEventSelection, s.signupPageviewEventSelection],
            (activityEventSelection, signupEventSelection, signupPageviewEventSelection): boolean => {
                return (
                    activityEventSelection !== null ||
                    signupEventSelection !== null ||
                    signupPageviewEventSelection !== null
                )
            },
        ],
        eventSelectors: [
            (s) => [s.activityEventFilters, s.signupEventFilters, s.signupPageviewEventFilters],
            (activityEventFilters, signupEventFilters, signupPageviewEventFilters): EventSelectorProps[] => [
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
            actions.updateEvents(events)
        },
        toggleModalOpen: ({ isOpen }) => {
            const isClosing = isOpen === false || (isOpen === undefined && values.isOpen)
            if (isClosing) {
                actions.setActivityEventSelection(null)
                actions.setSignupEventSelection(null)
                actions.setSignupPageviewEventSelection(null)
            }
        },
    })),
])
