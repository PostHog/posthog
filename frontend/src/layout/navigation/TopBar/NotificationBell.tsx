import React from 'react'
import { IconArrowDropDown, IconNotification, IconWithCount } from 'lib/components/icons'
import { notificationsLogic } from '~/layout/navigation/TopBar/notificationsLogic'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import { Popup } from 'lib/components/Popup/Popup'
import { LemonDivider } from 'lib/components/LemonDivider'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLog'
import './NotificationsBell.scss'

export function NotificationBell(): JSX.Element {
    const { unreadCount, hasImportantChanges, importantChanges, isNotificationPopoverOpen, hasUnread } =
        useValues(notificationsLogic)
    const { toggleNotificationsPopover, togglePolling } = useActions(notificationsLogic)

    usePageVisibility((pageIsVisible) => {
        togglePolling(pageIsVisible)
    })

    return (
        <Popup
            visible={isNotificationPopoverOpen}
            onClickOutside={toggleNotificationsPopover}
            overlay={
                <div className="activity-log notifications-menu">
                    <h5>Notifications</h5>
                    <LemonDivider />
                    {hasImportantChanges ? (
                        importantChanges.map((logItem, index) => <ActivityLogRow logItem={logItem} key={index} />)
                    ) : (
                        <h5>You're all caught up</h5>
                    )}
                </div>
            }
            className="NotificationsBell-Popup"
        >
            <div
                className={clsx('h-10 items-center cursor-pointer flex color-primary-alt text-2xl')}
                onClick={toggleNotificationsPopover}
                data-attr="notifications-button"
            >
                <IconWithCount count={unreadCount} showZero={true} status={hasUnread ? 'primary' : 'muted'}>
                    <IconNotification />
                </IconWithCount>
                <IconArrowDropDown />
            </div>
        </Popup>
    )
}
