import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { logsViewsList } from 'products/logs/frontend/generated/api'
import type { LogsViewApi } from 'products/logs/frontend/generated/api.schemas'

import type { logsWidgetSavedViewsLogicType } from './logsWidgetSavedViewsLogicType'

// One page is plenty — saved views are few, so we never paginate the dropdown.
const SAVED_VIEWS_LIMIT = 100

// Saved logs filters are LogsView rows ("saved views" on the logs page). The fetch is lazy —
// only tiles that actually surface the picker (feature flag on, or a saved view already persisted)
// trigger it, so tiles without the feature never hit the API.
export const logsWidgetSavedViewsLogic = kea<logsWidgetSavedViewsLogicType>([
    path(['products', 'dashboards', 'widgets', 'logs', 'logsWidgetSavedViewsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),
    actions({
        ensureSavedViewsLoaded: true,
    }),
    reducers({
        hasLoadedSavedViews: [false, { loadSavedViewsSuccess: () => true }],
    }),
    loaders(({ values }) => ({
        savedViews: {
            __default: [] as LogsViewApi[],
            loadSavedViews: async () => {
                const response = await logsViewsList(String(values.currentProjectId), { limit: SAVED_VIEWS_LIMIT })
                return response.results ?? []
            },
        },
    })),
    selectors({
        savedViewOptions: [
            (s) => [s.savedViews],
            (savedViews): { value: string; label: string }[] =>
                savedViews.map((view) => ({
                    value: view.short_id,
                    label: view.name || 'Unnamed view',
                })),
        ],
        // Single source for resolving a saved-view short_id to its display label, shared by the
        // tile filter bar and the read-only summary.
        savedViewLabelById: [
            (s) => [s.savedViewOptions],
            (savedViewOptions): Record<string, string> =>
                Object.fromEntries(savedViewOptions.map((option) => [option.value, option.label])),
        ],
    }),
    listeners(({ actions, values }) => ({
        ensureSavedViewsLoaded: () => {
            if (!values.hasLoadedSavedViews && !values.savedViewsLoading) {
                actions.loadSavedViews()
            }
        },
    })),
])
