import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { createFuse } from 'lib/utils/fuseSearch'
import { DataManagementTab } from 'scenes/data-management/DataManagementScene'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { actionsModel } from '~/models/actionsModel'
import { ActionType, ActivityScope, Breadcrumb } from '~/types'

import type { actionsLogicType } from './actionsLogicType'

export type ActionsFilterType = 'all' | 'me'

export const actionsFuse = createFuse<ActionType>([], {
    keys: [{ name: 'name', weight: 2 }, 'description', 'tags'],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
})

// Called from actionsLogic's connect() — before dependencies are mounted. We read the flag via
// findMounted() because featureFlagLogic is mounted at app bootstrap, long before the actions scene.
// If it's somehow not mounted yet, we safely fall back to the non-reference-count path.
export const getActionsModelParams = (): string => {
    const referenceCountEnabled =
        !!featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.ACTION_REFERENCE_COUNT]
    return referenceCountEnabled ? 'include_count=1&include_reference_count=1' : 'include_count=1'
}

export const actionsLogic = kea<actionsLogicType>([
    path(['products', 'actions', 'actionsLogic']),
    connect(() => ({
        values: [
            actionsModel({ params: getActionsModelParams() }),
            ['actions', 'actionsLoading'],
            userLogic,
            ['user'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),
    actions({
        setFilterType: (filterType: ActionsFilterType) => ({ filterType }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    reducers({
        filterType: [
            'all' as ActionsFilterType,
            { persist: true },
            {
                setFilterType: (_, { filterType }) => filterType,
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    }),
    selectors({
        actionsFiltered: [
            (s) => [s.actions, s.filterType, s.searchTerm, s.user],
            (actions, filterType, searchTerm, user) => {
                let data: ActionType[] = actions
                // Trim before handing the query to Fuse: a trailing space inflates the pattern
                // length, which raises the effective edit budget (threshold × length) and lets
                // unrelated items leak in (e.g. searching "mcp " matches "Map clicked").
                const trimmedSearchTerm = searchTerm.trim()
                if (trimmedSearchTerm) {
                    data = actionsFuse.search(trimmedSearchTerm).map((result) => result.item)
                }
                if (filterType === 'me') {
                    data = data.filter((item) => item.created_by?.uuid === user?.uuid)
                }
                return data
            },
        ],
        shouldShowEmptyState: [
            (s) => [s.actionsFiltered, s.actionsLoading, s.searchTerm],
            (actionsFiltered: ActionType[], actionsLoading: boolean, searchTerm: string): boolean => {
                return actionsFiltered.length == 0 && !actionsLoading && !searchTerm.length
            },
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        key: DataManagementTab.Actions,
                        name: 'Actions',
                        path: urls.actions(),
                        iconType: 'action',
                    },
                ]
            },
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => ({
                activity_scope: ActivityScope.ACTION,
            }),
        ],
    }),
    subscriptions({
        actions: (actions) => {
            actionsFuse.setCollection(actions)
        },
    }),
])
