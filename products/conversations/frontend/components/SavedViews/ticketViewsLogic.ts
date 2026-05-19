import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import type { SavedTicketView, TicketViewFilters } from '../../types'
import type { ticketViewsLogicType } from './ticketViewsLogicType'

export interface TicketViewsLogicProps {
    id: string
}

const viewsUrl = (teamId: number | null): string => `api/environments/${teamId}/conversations/views`

export const ticketViewsLogic = kea<ticketViewsLogicType>([
    props({} as TicketViewsLogicProps),
    key((props) => props.id),
    path((key) => ['products', 'conversations', 'frontend', 'components', 'SavedViews', 'ticketViewsLogic', key]),

    connect(() => ({
        values: [teamLogic, ['currentTeamId'], supportTicketsSceneLogic, ['currentFilters']],
        actions: [supportTicketsSceneLogic, ['applyViewFilters', 'setActiveView']],
    })),

    actions({
        deleteView: (shortId: string) => ({ shortId }),
        loadView: (view: SavedTicketView) => ({ view }),
        openModal: true,
        closeModal: true,
        openSaveModal: true,
        closeSaveModal: true,
        setViewName: (viewName: string) => ({ viewName }),
        saveView: true,
    }),

    loaders(({ values }) => ({
        views: [
            [] as SavedTicketView[],
            {
                loadViews: async () => {
                    // nosemgrep: prefer-codegen-api
                    const response = await api.get(viewsUrl(values.currentTeamId))
                    return response.results
                },
                createView: async ({ name, filters }: { name: string; filters: TicketViewFilters }) => {
                    // nosemgrep: prefer-codegen-api
                    const created: SavedTicketView = await api.create(viewsUrl(values.currentTeamId), {
                        name,
                        filters,
                    })
                    lemonToast.success('View saved')
                    return [created, ...values.views]
                },
            },
        ],
    })),

    reducers({
        views: {
            deleteView: (state, { shortId }) => state.filter((v) => v.short_id !== shortId),
        },
        isModalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
                loadView: () => false,
            },
        ],
        isSaveModalOpen: [
            false,
            {
                openSaveModal: () => true,
                closeSaveModal: () => false,
                createViewSuccess: () => false,
            },
        ],
        viewName: [
            '',
            {
                setViewName: (_, { viewName }) => viewName,
                closeSaveModal: () => '',
                createViewSuccess: () => '',
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        openModal: () => {
            actions.loadViews()
        },
        saveView: () => {
            const name = values.viewName.trim()
            if (!name) {
                return
            }
            actions.createView({ name, filters: { ...values.currentFilters } })
        },
        deleteView: async ({ shortId }) => {
            try {
                // nosemgrep: prefer-codegen-api
                await api.delete(`${viewsUrl(values.currentTeamId)}/${shortId}`)
                lemonToast.success('View deleted')
            } catch {
                lemonToast.error('Failed to delete view')
                actions.loadViews()
            }
        },
        loadView: ({ view }) => {
            actions.applyViewFilters(view.filters || {})
            actions.setActiveView(view)
        },
        createViewFailure: () => {
            lemonToast.error('Failed to save view')
        },
        loadViewsFailure: () => {
            lemonToast.error('Failed to load saved views')
        },
    })),
])
