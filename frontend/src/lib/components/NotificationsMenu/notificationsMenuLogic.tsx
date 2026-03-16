import { actions, kea, path, reducers } from 'kea'

import type { notificationsMenuLogicType } from './notificationsMenuLogicType'

export const notificationsMenuLogic = kea<notificationsMenuLogicType>([
    path(['lib', 'components', 'NotificationsMenu', 'notificationsMenuLogic']),
    actions({
        setNotificationsMenuOpen: (isOpen: boolean) => ({ isOpen }),
        toggleNotificationsMenu: true,
    }),
    reducers({
        isNotificationsMenuOpen: [
            false,
            {
                setNotificationsMenuOpen: (_, { isOpen }) => isOpen,
                toggleNotificationsMenu: (state) => !state,
            },
        ],
    }),
])
