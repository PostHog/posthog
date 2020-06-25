import { kea } from 'kea'
import { dockLogic } from '~/toolbar/dockLogic'

export const toolbarTabLogic = kea({
    actions: () => ({
        setTab: tab => ({ tab }),
    }),
    reducers: () => ({
        tab: [
            'stats',
            {
                setTab: (_, { tab }) => tab,
                [dockLogic.actions.button]: () => 'stats',
                [dockLogic.actions.float]: () => 'stats',
                [dockLogic.actions.dock]: () => 'stats',
            },
        ],
    }),
})
