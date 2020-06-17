import { kea } from 'kea'
import { dockLogic } from '~/toolbar/dockLogic'

export const toolbarTabLogic = kea({
    actions: () => ({
        setTab: tab => ({ tab }),
        setTabs: (tab, newTab) => ({ tab, newTab }),
    }),
    reducers: () => ({
        tab: [
            'stats',
            {
                setTabs: (_, { tab }) => tab,
            },
        ],
        newTab: [
            null,
            {
                setTabs: (_, { newTab }) => newTab,
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        setTab: async ({ tab }, breakpoint) => {
            // animate tab switching in dock mode
            if (dockLogic.values.mode === 'dock') {
                actions.setTabs(values.tab, tab)
                await breakpoint(200)
                actions.setTabs(null, tab)
                await breakpoint(200)
                actions.setTabs(tab, null)
            } else {
                actions.setTabs(tab, null)
            }
        },
    }),
})
