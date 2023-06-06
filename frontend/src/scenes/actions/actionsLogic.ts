import { kea, selectors, path, actions, reducers, connect } from 'kea'
import { Breadcrumb } from '~/types'
import { urls } from 'scenes/urls'

import type { actionsLogicType } from './actionsLogicType'
import { actionsModel } from '~/models/actionsModel'
import Fuse from 'fuse.js'
import { userLogic } from 'scenes/userLogic'

export const actionsLogic = kea<actionsLogicType>([
    path(['scenes', 'actions', 'actionsLogic']),
    connect({
        values: [actionsModel({ params: 'include_count=1' }), ['actions'], userLogic, ['user']],
    }),
    actions({
        setFilterByMe: (filterByMe: boolean) => ({ filterByMe }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    reducers({
        filterByMe: [
            false,
            { persist: true },
            {
                setFilterByMe: (_, { filterByMe }) => filterByMe,
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
            (s) => [s.actions, s.filterByMe, s.searchTerm, s.user],
            (actions, filterByMe, searchTerm, user) => {
                let data = actions
                if (searchTerm && searchTerm.length > 0) {
                    data = new Fuse(data, {
                        keys: ['name', 'url'],
                        threshold: 0.3,
                    })
                        .search(searchTerm)
                        .map((result) => result.item)
                }
                if (filterByMe) {
                    data = data.filter((item) => item.created_by?.uuid === user?.uuid)
                }
                return data
            },
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    name: `Data Management`,
                    path: urls.eventDefinitions(),
                },
                {
                    name: 'Actions',
                    path: urls.actions(),
                },
            ],
        ],
    }),
])
