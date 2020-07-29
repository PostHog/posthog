import { kea } from 'kea'
import { dockLogic } from '~/toolbar/dockLogic'
import { toolbarTabLogicType } from '~/toolbar/toolbarTabLogicType'
import { ToolbarTab } from '~/types'

export const toolbarTabLogic = kea<toolbarTabLogicType<ToolbarTab>>({
    actions: () => ({
        setTab: (tab: ToolbarTab) => ({ tab }),
    }),
    reducers: () => ({
        tab: [
            'stats' as ToolbarTab,
            {
                setTab: (_, { tab }) => tab,
                [dockLogic.actionTypes.button]: () => 'stats',
                [dockLogic.actionTypes.dock]: () => 'stats',
            },
        ],
    }),
})
