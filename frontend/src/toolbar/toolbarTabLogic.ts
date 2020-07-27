import { kea } from 'kea'
import { dockLogic } from '~/toolbar/dockLogic'
import { toolbarTabLogicType } from '~/toolbar/toolbarTabLogicType'

export const toolbarTabLogic = kea<toolbarTabLogicType>({
    actions: () => ({
        setTab: (tab: string) => ({ tab }),
    }),
    reducers: () => ({
        tab: [
            'stats',
            {
                setTab: (_, { tab }) => tab,
                [dockLogic.actionTypes.button]: () => 'stats',
                [dockLogic.actionTypes.dock]: () => 'stats',
            },
        ],
    }),
})
