import { actions, kea, path, reducers } from 'kea'

import type { topBarLogicType } from './topBarLogicType'

export const topBarLogic = kea<topBarLogicType>([
    path(['layout', 'navigation', 'TopBar', 'topBarLogic']),
    actions({
        toggleProjectSwitcher: true,
        hideProjectSwitcher: true,
    }),
    reducers({
        isProjectSwitcherShown: [
            false,
            {
                toggleProjectSwitcher: (state) => !state,
                hideProjectSwitcher: () => false,
            },
        ],
    }),
])
