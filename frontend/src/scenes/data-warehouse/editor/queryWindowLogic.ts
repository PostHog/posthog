import { actions, events, kea, listeners, path, reducers } from 'kea'
import { uuid } from 'lib/utils'

import type { queryWindowLogicType } from './queryWindowLogicType'

export interface Tab {
    key: string
    label: string
}

export const queryWindowLogic = kea<queryWindowLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'queryWindowLogic']),
    actions({
        selectTab: (tab: Tab) => ({ tab }),
        addTab: true,
        _addTab: (tab: Tab) => ({ tab }),
        deleteTab: (tab: Tab) => ({ tab }),
        _deleteTab: (tab: Tab) => ({ tab }),
    }),
    reducers({
        tabs: [
            [] as Tab[],
            {
                _addTab: (state, { tab }) => [...state, tab],
                _deleteTab: (state, { tab }) => state.filter((t) => t.key !== tab.key),
            },
        ],
        activeTabKey: [
            'none',
            {
                selectTab: (_, { tab }) => tab.key,
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        addTab: () => {
            const tab = {
                key: uuid(),
                label: 'Untitled',
            }
            actions._addTab(tab)
            actions.selectTab(tab)
        },
        deleteTab: ({ tab }) => {
            if (tab.key === values.activeTabKey) {
                const indexOfTab = values.tabs.findIndex((t) => t.key === tab.key)
                const nextTab = values.tabs[indexOfTab + 1] || values.tabs[indexOfTab - 1] || values.tabs[0]
                actions.selectTab(nextTab)
            }
            actions._deleteTab(tab)
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.addTab()
        },
    })),
])
