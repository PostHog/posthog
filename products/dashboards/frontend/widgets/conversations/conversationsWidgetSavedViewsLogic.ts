import { MakeLogicType, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { teamLogic } from 'scenes/teamLogic'

import { conversationsViewsList } from 'products/conversations/frontend/generated/api'
import type { TicketViewApi } from 'products/conversations/frontend/generated/api.schemas'

const SAVED_VIEWS_PAGE_SIZE = 100
const SAVED_VIEWS_MAX_RESULTS = 500

export interface conversationsWidgetSavedViewsLogicValues {
    currentProjectId: number | string
    savedViewsError: string | null
    savedViewLabelById: Record<string, string>
    savedViewOptions: { label: string; value: string }[]
    savedViews: TicketViewApi[]
    savedViewsLoading: boolean
}

export interface conversationsWidgetSavedViewsLogicActions {
    loadSavedViews: () => void
    loadSavedViewsFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    loadSavedViewsSuccess: (savedViews: TicketViewApi[]) => { savedViews: TicketViewApi[] }
}

export interface conversationsWidgetSavedViewsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        savedViewOptions: (savedViews: TicketViewApi[]) => { label: string; value: string }[]
        savedViewLabelById: (options: { label: string; value: string }[]) => Record<string, string>
    }
}

export type conversationsWidgetSavedViewsLogicType = MakeLogicType<
    conversationsWidgetSavedViewsLogicValues,
    conversationsWidgetSavedViewsLogicActions,
    Record<string, never>,
    conversationsWidgetSavedViewsLogicMeta
>

export const conversationsWidgetSavedViewsLogic = kea<conversationsWidgetSavedViewsLogicType>([
    path(['products', 'dashboards', 'widgets', 'conversations', 'conversationsWidgetSavedViewsLogic']),
    connect(() => ({ values: [teamLogic, ['currentProjectId']] })),
    loaders(({ values }) => ({
        savedViews: {
            __default: [] as TicketViewApi[],
            loadSavedViews: async () => {
                const savedViews: TicketViewApi[] = []
                for (let offset = 0; offset < SAVED_VIEWS_MAX_RESULTS; offset += SAVED_VIEWS_PAGE_SIZE) {
                    const response = await conversationsViewsList(String(values.currentProjectId), {
                        limit: SAVED_VIEWS_PAGE_SIZE,
                        offset,
                    })
                    savedViews.push(...response.results)
                    if (!response.next) {
                        break
                    }
                }
                return savedViews
            },
        },
    })),
    reducers({
        savedViewsError: [
            null as string | null,
            {
                loadSavedViews: () => null,
                loadSavedViewsFailure: (_, { error }) => error,
                loadSavedViewsSuccess: () => null,
            },
        ],
    }),
    selectors({
        savedViewOptions: [
            (selectors) => [selectors.savedViews],
            (savedViews: TicketViewApi[]): { label: string; value: string }[] =>
                savedViews.map((view) => ({ value: view.short_id, label: view.name })),
        ],
        savedViewLabelById: [
            (selectors) => [selectors.savedViewOptions],
            (options: { label: string; value: string }[]): Record<string, string> =>
                Object.fromEntries(options.map((option) => [option.value, option.label])),
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadSavedViews()
    }),
    subscriptions(({ actions }) => ({
        currentProjectId: () => actions.loadSavedViews(),
    })),
])
