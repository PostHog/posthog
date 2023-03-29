import { actions, kea, path, reducers } from 'kea'

export const automationStepMenuLogic = kea([
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
