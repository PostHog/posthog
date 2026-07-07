import { actions, connect, kea, listeners, path, reducers } from 'kea'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import type { notificationsMenuLogicType } from './notificationsMenuLogicType'

export type NotificationTab = 'all' | 'unread'

export const notificationsMenuLogic = kea<notificationsMenuLogicType>([
    path(['lib', 'components', 'NotificationsMenu', 'notificationsMenuLogic']),
    connect(() => ({
        actions: [panelLayoutLogic, ['setActivePanelIdentifier', 'showLayoutPanel']],
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
        openToUnread: () => {
            // The Notifications side panel's visibility is owned by panelLayoutLogic, so opening it
            // (e.g. from a critical-notification toast button) has to go through these actions.
            actions.setActivePanelIdentifier('Notifications')
            actions.showLayoutPanel(true)
        },
    })),
])
