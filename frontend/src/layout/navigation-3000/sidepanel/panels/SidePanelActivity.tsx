import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonDivider, LemonTag, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLog'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { urls } from 'scenes/urls'

import { notificationsLogic } from '~/layout/navigation/TopBar/notificationsLogic'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'

export const SidePanelActivity = (): JSX.Element => {
    const { hasNotifications, notifications } = useValues(notificationsLogic)
    const { togglePolling } = useActions(notificationsLogic)

    usePageVisibility((pageIsVisible) => {
        togglePolling(pageIsVisible)
    })

    return (
        <div className="flex flex-col overflow-hidden">
            <SidePanelPaneHeader
                title={
                    <>
                        Activity{' '}
                        <LemonTag type="warning" className="ml-1">
                            Beta
                        </LemonTag>
                    </>
                }
            />
            <div className="flex flex-col overflow-y-auto p-2">
                <LemonBanner type="info">
                    {/* <p className={'mx-2 text-muted mt-2'}> */}
                    Notifications shows you changes others make to{' '}
                    <Link to={urls.savedInsights('history')}>Insights</Link> and{' '}
                    <Link to={urls.featureFlags('history')}>Feature Flags</Link> that you created. Come join{' '}
                    <Link to={'https://posthog.com/community'}>our community forum</Link> and tell us what else should
                    be here!
                    {/* </p> */}
                </LemonBanner>
                <LemonDivider />
                {hasNotifications ? (
                    notifications.map((logItem, index) => (
                        <ActivityLogRow logItem={logItem} key={index} showExtendedDescription={false} />
                    ))
                ) : (
                    <h5>You're all caught up</h5>
                )}
            </div>
        </div>
    )
}
