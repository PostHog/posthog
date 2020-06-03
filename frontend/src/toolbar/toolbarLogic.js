import { kea } from 'kea'

export const toolbarLogic = kea({
    actions: () => ({
        setTab: tab => ({ tab }),
        removeOldTab: true,
        removeNewTab: tab => ({ tab }),
    }),
    reducers: () => ({
        tab: [
            'stats',
            {
                removeOldTab: () => null,
                removeNewTab: (_, { tab }) => tab,
            },
        ],
        newTab: [
            null,
            {
                setTab: (_, { tab }) => tab,
                removeNewTab: () => null,
            },
        ],
    }),
    listeners: ({ actions }) => ({
        setTab: async ({ tab }, breakpoint) => {
            await breakpoint(200)
            actions.removeOldTab()
            await breakpoint(200)
            actions.removeNewTab(tab)
        },
    }),
})
