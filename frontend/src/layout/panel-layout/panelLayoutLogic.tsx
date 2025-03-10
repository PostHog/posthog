import { kea } from 'kea'

import type { panelLayoutLogicType } from './panelLayoutLogicType'

export const panelLayoutLogic = kea<panelLayoutLogicType>({
    path: ['layout', 'panel-layout', 'panelLayoutLogic'],
    actions: {
        setProjectTreeMode: (projectTreeMode: 'tree' | 'table') => ({ projectTreeMode }),
    },
    reducers: {
        projectTreeMode: [
            'tree' as 'tree' | 'table',
            { persist: true },
            { setProjectTreeMode: (_, { projectTreeMode }) => projectTreeMode },
        ],
    },
})
