import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { EventType } from '~/types'

import type { feedbackLogicType } from './feedbackLogicType'

export const feedbackLogic = kea<feedbackLogicType>([
    path(['scenes', 'feedback', 'feedbackLogic']),
    actions({
        setTab: (activeTab: string) => ({ activeTab }),
        toggleInAppFeedbackInstructions: true,
        setExpandedSection: (idx: number, expanded: boolean) => ({ idx, expanded }),
    }),
    reducers({
        activeTab: [
            'in-app-feedback' as string,
            {
                setTab: (_, { activeTab }) => activeTab,
            },
        ],
        inAppFeedbackInstructions: [
            false,
            {
                toggleInAppFeedbackInstructions: (state) => !state,
            },
        ],
        expandedSections: [
            [true, false] as boolean[],
            {
                setExpandedSection: (state, { idx, expanded }) => {
                    // set all to false apart from the one we're changing
                    return state.map((_, i) => (i === idx ? expanded : false))
                },
            },
        ],
    }),
    loaders({
        events: {
            loadEvents: async ({ eventName }: { eventName: string }) => {
                const response = await api.events.list({
                    properties: [],
                    event: eventName,
                    orderBy: ['-timestamp'],
                })

                // TODO: fix this type
                return response.results as unknown as EventType[]
            },
        },
    }),
    selectors({
        expandedSection: [
            (s) => [s.expandedSections],
            (expandedSections: boolean[]) => (idx: number) => expandedSections[idx],
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadEvents({
            eventName: 'Feedback Sent',
        })
    }),
])
