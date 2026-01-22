import { actions, kea, path, reducers } from 'kea'

import type { commandLogicType } from './commandLogicType'

export const commandLogic = kea<commandLogicType>([
    path(['lib', 'components', 'Command', 'commandLogic']),
    actions({
        openCommand: true,
        closeCommand: true,
        toggleCommand: true,
    }),
    reducers({
        isCommandOpen: [
            false,
            {
                openCommand: () => true,
                closeCommand: () => false,
                toggleCommand: (state) => !state,
            },
        ],
    }),
])
