import Fuse from 'fuse.js'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'
import { subscriptions } from 'kea-subscriptions'
import { actionsModel } from '~/models/actionsModel'
import { ActionType, Breadcrumb } from '~/types'
import { Scene } from 'scenes/sceneTypes'
import type { actionsLogicType } from './actionsLogicType'
import { urls } from 'scenes/urls'

import { DataManagementTab } from 'scenes/data-management/DataManagementScene'

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
                        key: Scene.DataManagement,
                        name: `Data management`,
                        path: urls.eventDefinitions(),
                    },
                    {
                        key: DataManagementTab.Actions,
                        name: 'Actions',
                        path: urls.actions(),
                    },
                ]
            },
        ],
    }),
    subscriptions({
        actions: (actions) => {
            actionsFuse.setCollection(actions)
        },
    }),
])
