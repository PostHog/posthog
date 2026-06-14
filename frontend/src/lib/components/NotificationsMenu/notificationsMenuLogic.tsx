import { actions, connect, kea, listeners, path, reducers } from 'kea'

import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'

import type { notificationsMenuLogicType } from './notificationsMenuLogicType'

export type NotificationTab = 'all' | 'unread' | 'archived'

export const notificationsMenuLogic = kea<notificationsMenuLogicType>([
    path(['lib', 'components', 'NotificationsMenu', 'notificationsMenuLogic']),
    connect(() => ({
        actions: [sidePanelNotificationsLogic, ['loadArchivedNotifications']],
    })),
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
    listeners(({ actions }) => ({
        setActiveTab: ({ tab }) => {
            // Archived notifications are a separate data source loaded on demand. Refetch every time
            // the tab is opened so items just archived from the other tabs always show up.
            if (tab === 'archived') {
                actions.loadArchivedNotifications()
            }
        },
    })),
])
