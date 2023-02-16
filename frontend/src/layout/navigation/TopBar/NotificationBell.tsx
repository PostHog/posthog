import { IconArrowDropDown, IconInfo, IconNotification, IconRefresh, IconWithCount } from 'lib/lemon-ui/icons'
import { notificationsLogic } from '~/layout/navigation/TopBar/notificationsLogic'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLog'
import './NotificationsBell.scss'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

export function NotificationBell(): JSX.Element {
    const {
        unreadCount,
        hasImportantChanges,
        importantChanges,
        isNotificationPopoverOpen,
        hasUnread,
        importantChangesLoading,
    } = useValues(notificationsLogic)
    const { toggleNotificationsPopover, togglePolling, loadImportantChanges } = useActions(notificationsLogic)

    usePageVisibility((pageIsVisible) => {
        togglePolling(pageIsVisible)
    })

    return (
        <Popover
            visible={isNotificationPopoverOpen}
            onClickOutside={toggleNotificationsPopover}
            overlay={
                <div className="activity-log notifications-menu">
                    <h5 className={'flex flex-row justify-between items-center'}>
                        <div>
                            Notifications{' '}
                            <LemonTag type="warning" className="ml-1">
                                Beta
                            </LemonTag>
                        </div>
                        <LemonButton
                            size={'small'}
                            type={'secondary'}
                            onClick={loadImportantChanges}
                            icon={importantChangesLoading ? <Spinner monocolor={true} /> : <IconRefresh />}
                            disabledReason={
                                hasUnread
                                    ? 'No need to check, you have unread changes.'
                                    : importantChangesLoading
                                    ? 'Checking for changes'
                                    : false
                            }
                            data-attr="check-for-important-changes-button"
                        >
                            Check for changes
                        </LemonButton>
                    </h5>
                    <p className={'mx-2 text-muted mt-2'}>
                        <IconInfo /> Notifications is in beta. Right now it only shows you changes other users make to{' '}
                        <Link to={urls.savedInsights('history')}>Insights</Link> and{' '}
                        <Link to={urls.featureFlags('history')}>Feature Flags</Link> that you created. Come join{' '}
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
            className="NotificationsBell-Popover"
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
        </Popover>
    )
}
