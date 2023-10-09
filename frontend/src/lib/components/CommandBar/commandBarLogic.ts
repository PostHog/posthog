import { kea, path, actions, reducers } from 'kea'
import { BarStatus } from './types'

import type { commandBarLogicType } from './commandBarLogicType'

export const commandBarLogic = kea<commandBarLogicType>([
    path(['lib', 'components', 'CommandBar', 'commandBarLogic']),
    actions({
        hideCommandBar: true,
        toggleSearchBar: true,
        toggleActionsBar: true,
    }),
    reducers({
        barStatus: [
            BarStatus.HIDDEN as BarStatus,
            {
                hideCommandBar: () => BarStatus.HIDDEN,
                toggleSearchBar: (previousState) =>
                    previousState === BarStatus.HIDDEN ? BarStatus.SHOW_SEARCH : BarStatus.HIDDEN,
                toggleActionsBar: (previousState) =>
                    previousState === BarStatus.HIDDEN ? BarStatus.SHOW_ACTIONS : BarStatus.HIDDEN,
            },
        ],
    }),
])
