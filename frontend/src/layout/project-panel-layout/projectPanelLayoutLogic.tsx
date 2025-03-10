import { kea } from 'kea'

import type { projectPanelLayoutLogicType } from './projectPanelLayoutLogicType'

export const projectPanelLayoutLogic = kea<projectPanelLayoutLogicType>({
    path: ['layout', 'project-panel-layout', 'projectPanelLayoutLogic'],
    actions: {
        togglePanelVisible: (visible: boolean) => ({ visible }),
        togglePanelPinned: (pinned: boolean) => ({ pinned }),
    },
    reducers: {
        isPanelVisible: [
            false,
            {
                togglePanelVisible: (_, { visible }) => visible,
                togglePanelPinned: (_, { pinned }) => pinned || _,
            },
        ],
        isPanelPinned: [false, { togglePanelPinned: (_, { pinned }) => pinned }],
    },
})
