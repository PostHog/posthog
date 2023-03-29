import { actions, kea, path, reducers } from 'kea'

import type { automationStepMenuLogicType } from './automationStepMenuLogicType'

export const automationStepMenuLogic = kea<automationStepMenuLogicType>([
    path(['scenes', 'automations', 'AutomationStepSidebard', 'automationStepMenuLogic']),
    actions({
        openMenu: true,
        closeMenu: true,
    }),
    reducers({
        isMenuOpen: [
            true as boolean,
            {
                openMenu: () => true,
                closeMenu: () => false,
            },
        ],
    }),
])
