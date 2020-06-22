import { kea } from 'kea'

export const toolbarTabLogic = kea({
    actions: () => ({
        setTab: tab => ({ tab }),
    }),
    reducers: () => ({
        tab: [
            'stats',
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    }),
})
