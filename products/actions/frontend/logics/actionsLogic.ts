import Fuse from 'fuse.js'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DataManagementTab } from 'scenes/data-management/DataManagementScene'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { actionsModel } from '~/models/actionsModel'
import { ActionType, ActivityScope, Breadcrumb } from '~/types'

import type { actionsLogicType } from './actionsLogicType'

export type ActionsFilterType = 'all' | 'me'

export const actionsFuse = new Fuse<ActionType>([], {
    keys: [{ name: 'name', weight: 2 }, 'description', 'tags'],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
})

export const actionsLogic = kea<actionsLogicType>([
    path(['products', 'actions', 'actionsLogic']),
    connect(() => ({
        values: [
            actionsModel({ params: 'include_count=1' }),
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
                if (searchTerm) {
                    data = actionsFuse.search(searchTerm).map((result) => result.item)
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
