import { IconArrowDropDown, IconInfo, IconNotification, IconWithCount } from 'lib/lemon-ui/icons'
import { notificationsLogic } from '~/layout/navigation/TopBar/notificationsLogic'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import { Popup } from 'lib/lemon-ui/Popup/Popup'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLog'
import './NotificationsBell.scss'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'

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
                    <h5>
                        Notifications{' '}
                        <LemonTag type="warning" className="ml-1">
                            Beta
                        </LemonTag>
                    </h5>
                    <p className={'mx-2 text-muted'}>
                        <IconInfo /> Notifications is in beta. Right now it only shows you changes other users make to
                        Insights and Feature Flags that you created. Come join{' '}
                        <Link to={'https://posthog.com/slack'}>our community slack</Link> and tell us what else should
                        be here!
                    </p>
                    <LemonDivider />
                    {hasImportantChanges ? (
                        importantChanges.map((logItem, index) => (
                            <ActivityLogRow logItem={logItem} key={index} showExtendedDescription={false} />
                        ))
                    ) : (
                        <h5>You're all caught up</h5>
                    )}
                </div>
            }
            className="NotificationsBell-Popup"
        >
            <div
                className={clsx('h-10 items-center cursor-pointer flex text-primary-alt text-2xl')}
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
