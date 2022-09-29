import React from 'react'
import { IconArrowDropDown, IconNotification, IconWithCount } from 'lib/components/icons'
import { notificationsLogic } from '~/layout/navigation/TopBar/notificationsLogic'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import { Popup } from 'lib/components/Popup/Popup'
import { LemonDivider } from 'lib/components/LemonDivider'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLog'

export function NotificationBell(): JSX.Element {
    const { importantChanges, isNotificationPopoverOpen } = useValues(notificationsLogic)
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
                    {importantChanges.map((logItem, index) => (
                        <ActivityLogRow logItem={logItem} key={index} />
                    ))}
                </div>
            }
        >
            <div
                className={clsx('h-10 items-center cursor-pointer flex color-primary-alt text-2xl')}
                onClick={toggleNotificationsPopover}
                data-attr="notifications-button"
            >
                <IconWithCount count={importantChanges.length || 0} showZero={false} status={'danger'}>
                    <IconNotification />
                </IconWithCount>
                <IconArrowDropDown />
            </div>
        </Popup>
    )
}
