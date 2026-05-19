import { actions, kea, path, reducers } from 'kea'

import type { newAccountMenuLogicType } from './newAccountMenuLogicType'

export const newAccountMenuLogic = kea<newAccountMenuLogicType>([
    path(['lib', 'components', 'Account', 'accountMenuLogic']),
    actions({
        setAccountMenuOpen: (isOpen: boolean) => ({ isOpen }),
        toggleAccountMenu: true,
        // Project switcher modal
        openProjectSwitcher: true,
        closeProjectSwitcher: true,
        toggleProjectSwitcher: true,
        // Org switcher modal
        openOrgSwitcher: true,
        closeOrgSwitcher: true,
        toggleOrgSwitcher: true,
    }),
    reducers({
        isAccountMenuOpen: [
            false,
            {
                setAccountMenuOpen: (_, { isOpen }) => isOpen,
                toggleAccountMenu: (state) => !state,
            },
        ],
        isProjectSwitcherOpen: [
            false,
            {
                openProjectSwitcher: () => true,
                closeProjectSwitcher: () => false,
                toggleProjectSwitcher: (state) => !state,
            },
        ],
        isOrgSwitcherOpen: [
            false,
            {
                openOrgSwitcher: () => true,
                closeOrgSwitcher: () => false,
                toggleOrgSwitcher: (state) => !state,
            },
        ],
    }),
])
