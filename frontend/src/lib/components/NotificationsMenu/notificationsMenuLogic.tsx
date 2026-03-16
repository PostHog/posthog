import { actions, kea, listeners, path, reducers } from 'kea'

import type { notificationsMenuLogicType } from './notificationsMenuLogicType'

export type NotificationTab = 'all' | 'unread'

export const notificationsMenuLogic = kea<notificationsMenuLogicType>([
    path(['lib', 'components', 'NotificationsMenu', 'notificationsMenuLogic']),
    actions({
        setNotificationsMenuOpen: (isOpen: boolean) => ({ isOpen }),
        toggleNotificationsMenu: true,
        setActiveTab: (tab: NotificationTab) => ({ tab }),
        openToUnread: true,
    }),
    reducers({
        isNotificationsMenuOpen: [
            false as boolean,
            {
                setNotificationsMenuOpen: (_, { isOpen }) => isOpen,
                toggleNotificationsMenu: (state) => !state,
                openToUnread: () => true,
            },
        ],
        activeTab: [
            'all' as NotificationTab,
            {
                setActiveTab: (_, { tab }) => tab,
                openToUnread: () => 'unread' as NotificationTab,
            },
        ],
    }),
    listeners({
        setNotificationsMenuOpen: ({ isOpen }) => {
            // Reset to "all" tab when closing
            if (!isOpen) {
                // No-op — keep tab selection sticky
            }
        },
    }),
])
