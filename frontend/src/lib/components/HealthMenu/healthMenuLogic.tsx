import { actions, kea, path, reducers } from 'kea'

import type { healthMenuLogicType } from './healthMenuLogicType'

export const healthMenuLogic = kea<healthMenuLogicType>([
    path(['lib', 'components', 'HealthMenu', 'healthMenuLogic']),
    actions({
        setHealthMenuOpen: (isOpen: boolean) => ({ isOpen }),
        toggleHealthMenu: true,
    }),
    reducers({
        isHealthMenuOpen: [
            false,
            {
                setHealthMenuOpen: (_, { isOpen }) => isOpen,
                toggleHealthMenu: (state) => !state,
            },
        ],
    }),
])
