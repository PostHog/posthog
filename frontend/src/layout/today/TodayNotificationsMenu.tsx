import { useActions, useValues } from 'kea'

import { IconNotification } from '@posthog/icons'
import { Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { notificationsMenuLogic } from 'lib/components/NotificationsMenu/notificationsMenuLogic'

import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'

import { TodayNotificationsPanel } from './TodayNotificationsPanel'
import { TodayRailTile } from './TodayRailTile'

/** The rail's notifications tile. It opens the list in a popover, where the classic layout opens a left panel. */
export function TodayNotificationsMenu(): JSX.Element {
    const { isNotificationsPanelActive } = useValues(notificationsMenuLogic)
    const { openNotificationsPanel, closeNotificationsPanel } = useActions(notificationsMenuLogic)
    const { inAppUnreadCount } = useValues(sidePanelNotificationsLogic)

    return (
        <Popover
            open={isNotificationsPanelActive}
            onOpenChange={(open) => (open ? openNotificationsPanel('bell') : closeNotificationsPanel())}
        >
            <PopoverTrigger
                render={
                    <TodayRailTile
                        label="Notifications"
                        aria-label={
                            inAppUnreadCount > 0 ? `Notifications, ${inAppUnreadCount} unread` : 'Notifications'
                        }
                        icon={<IconNotification />}
                        active={isNotificationsPanelActive}
                        // pinned: autocapture data-attr of the classic bell
                        dataAttr="notifications-menu-button"
                        severity={inAppUnreadCount > 0 ? 'notice' : 'none'}
                    />
                }
            />
            <PopoverContent side="right" align="end" className="flex max-h-144 w-96 flex-col p-0">
                <TodayNotificationsPanel onNavigate={closeNotificationsPanel} />
            </PopoverContent>
        </Popover>
    )
}
