import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { CoreEvent } from '~/queries/schema/schema-general'

import type { coreEventsLogicType } from './coreEventsLogicType'

/** API response type for core events */
interface CoreEventResponse {
    id: string
    name: string
    description: string
    category: string
    filter: Record<string, unknown>
    created_at: string
    updated_at: string
}

/** Convert API response to CoreEvent type */
function toCoreEvent(response: CoreEventResponse): CoreEvent {
    return {
        id: response.id,
        name: response.name,
        description: response.description,
        category: response.category as CoreEvent['category'],
        filter: response.filter as unknown as CoreEvent['filter'],
    }
}

export const coreEventsLogic = kea<coreEventsLogicType>([
    path(['scenes', 'settings', 'environment', 'coreEventsLogic']),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    actions({
        setCoreEvents: (events: CoreEvent[]) => ({ events }),
        addCoreEvent: (event: Omit<CoreEvent, 'id'>) => ({ event }),
        updateCoreEvent: (event: CoreEvent) => ({ event }),
        removeCoreEvent: (eventId: string) => ({ eventId }),
    }),
    reducers({
        coreEvents: [
            [] as CoreEvent[],
            {
                setCoreEvents: (_, { events }) => events,
            },
        ],
    }),
    loaders(({ values, actions }) => ({
        coreEventsLoader: {
            loadCoreEvents: async () => {
                if (!values.currentTeamId) {
                    return []
                }
                try {
                    const response = await api.get(`api/environments/${values.currentTeamId}/core_events/`)
                    const events = (response.results || []).map(toCoreEvent)
                    actions.setCoreEvents(events)
                    return events
                } catch {
                    return []
                }
            },
        },
    })),
    selectors({
        coreEventsLoading: [(s) => [s.coreEventsLoaderLoading], (loading: boolean) => loading],
    }),
    listeners(({ values, actions }) => ({
        addCoreEvent: async ({ event }) => {
            if (!values.currentTeamId) {
                return
            }
            try {
                await api.create(`api/environments/${values.currentTeamId}/core_events/`, event)
                actions.loadCoreEvents()
                lemonToast.success('Core event added')
            } catch {
                lemonToast.error('Failed to add core event')
            }
        },
        updateCoreEvent: async ({ event }) => {
            if (!values.currentTeamId) {
                return
            }
            try {
                await api.update(`api/environments/${values.currentTeamId}/core_events/${event.id}/`, event)
                actions.loadCoreEvents()
                lemonToast.success('Core event updated')
            } catch {
                lemonToast.error('Failed to update core event')
            }
        },
        removeCoreEvent: async ({ eventId }) => {
            if (!values.currentTeamId) {
                return
            }
            try {
                await api.delete(`api/environments/${values.currentTeamId}/core_events/${eventId}/`)
                actions.loadCoreEvents()
                lemonToast.success('Core event removed')
            } catch {
                lemonToast.error('Failed to remove core event')
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadCoreEvents()
    }),
])
