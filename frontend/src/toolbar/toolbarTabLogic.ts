import { kea } from 'kea'
import { dockLogic } from '~/toolbar/dockLogic'
import { toolbarTabLogicType } from '~/toolbar/toolbarTabLogic.type'

export const toolbarTabLogic = kea<toolbarTabLogicType>({
    actions: () => ({
        setTab: (tab: string) => ({ tab }),
    }),
    reducers: () => ({
        tab: [
            'stats',
            {
                setTab: (_, { tab }) => tab,
                [dockLogic.actions.button]: () => 'stats',
                [dockLogic.actions.dock]: () => 'stats',
            },
        ],
    }),
})
