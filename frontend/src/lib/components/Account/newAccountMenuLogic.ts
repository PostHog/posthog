import { actions, kea, path, reducers } from 'kea'

import type { newAccountMenuLogicType } from './newAccountMenuLogicType'

export const newAccountMenuLogic = kea<newAccountMenuLogicType>([
    path(['lib', 'components', 'Account', 'accountMenuLogic']),
    actions({
        setAccountMenuOpen: (isOpen: boolean) => ({ isOpen }),
        toggleAccountMenu: true,
    }),
    reducers({
        isAccountMenuOpen: [
            false,
            {
                setAccountMenuOpen: (_, { isOpen }) => isOpen,
                toggleAccountMenu: (state) => !state,
            },
        ],
    }),
])
