import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { automationStepConfigLogic } from './automationStepConfigLogic'

import type { automationStepMenuLogicType } from './automationStepMenuLogicType'

export const automationStepMenuLogic = kea<automationStepMenuLogicType>([
    path(['scenes', 'automations', 'AutomationStepSidebard', 'automationStepMenuLogic']),
    connect({
        actions: [automationStepConfigLogic, ['setActiveStepId']],
    }),
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
    // connect to automationStepConfigLogic to set the active step as null when a menu is opened
    listeners(({ actions }) => ({
        openMenu: () => {
            actions.setActiveStepId(null)
        },
    })),
])
