import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { seriesToActionsAndEvents } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { isDataWarehouseNode } from '~/queries/utils'
import { FilterType, InsightType } from '~/types'

import { customerAnalyticsConfigLogic } from 'products/customer_analytics/frontend/customerAnalyticsConfigLogic'

import type { eventConfigModalLogicType } from './eventConfigModalLogicType'

export const eventConfigModalLogic = kea<eventConfigModalLogicType>([
    path(['products', 'customerAnalytics', 'components', 'insights', 'eventConfigModal']),
    connect(() => ({
        values: [
            customerAnalyticsConfigLogic,
            ['activityEvent', 'signupEvent', 'signupPageviewEvent', 'subscriptionEvent', 'paymentEvent'],
        ],
        actions: [customerAnalyticsConfigLogic, ['updateActivityEvent']],
    })),
    actions({
        setActivityEventSelection: (filters: FilterType | null) => ({
            filters,
        }),
        saveActivityEvent: true,
        toggleModalOpen: (isOpen?: boolean) => ({ isOpen }),
    }),
    reducers({
        activityEventSelection: [
            null as FilterType | null,
            {
                setActivityEventSelection: (_, { filters }) => filters,
            },
        ],
        isOpen: [
            false,
            {
                toggleModalOpen: (state, { isOpen }) => (isOpen !== undefined ? isOpen : !state),
            },
        ],
    }),
    selectors({
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
        hasActivityEventChanged: [
            (s) => [s.activityEventSelection],
            (activityEventSelection): boolean => {
                return activityEventSelection !== null
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        saveActivityEvent: () => {
            const filters = values.activityEventSelection
            const activityEvents = actionsAndEventsToSeries(filters as any, true, MathAvailability.None)

            if (activityEvents.length > 0 && !isDataWarehouseNode(activityEvents[0])) {
                actions.updateActivityEvent(activityEvents[0])
                actions.setActivityEventSelection(null)
            }
        },
        toggleModalOpen: ({ isOpen }) => {
            const isClosing = isOpen === false || (isOpen === undefined && values.isOpen)
            if (isClosing) {
                actions.setActivityEventSelection(null)
            }
        },
    })),
])
