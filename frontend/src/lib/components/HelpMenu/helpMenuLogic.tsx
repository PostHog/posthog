import { actions, kea, path, reducers } from 'kea'

import type { helpMenuLogicType } from './helpMenuLogicType'

export const helpMenuLogic = kea<helpMenuLogicType>([
    path(['lib', 'components', 'HelpMenu', 'helpMenuLogic']),
    actions({
        setHelpMenuOpen: (isOpen: boolean) => ({ isOpen }),
        toggleHelpMenu: true,
    }),
    reducers({
        isHelpMenuOpen: [
            false,
            {
                setHelpMenuOpen: (_, { isOpen }) => isOpen,
                toggleHelpMenu: (state) => !state,
            },
        ],
    }),
])
