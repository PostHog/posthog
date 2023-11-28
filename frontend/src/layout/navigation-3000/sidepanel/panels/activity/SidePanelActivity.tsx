import { LemonBanner, LemonTag, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLog'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { useEffect } from 'react'
import { urls } from 'scenes/urls'

import { notificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/notificationsLogic'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'

export const SidePanelActivity = (): JSX.Element => {
    const { hasNotifications, notifications } = useValues(notificationsLogic)
    const { togglePolling } = useActions(notificationsLogic)

    usePageVisibility((pageIsVisible) => {
        togglePolling(pageIsVisible)
    })

    useEffect(() => {
        return () => {
            togglePolling(false)
        }
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
                    Notifications shows you changes others make to{' '}
                    <Link to={urls.savedInsights('history')}>Insights</Link> and{' '}
                    <Link to={urls.featureFlags('history')}>Feature Flags</Link> that you created. Come join{' '}
                    <Link to={'https://posthog.com/community'}>our community forum</Link> and tell us what else should
                    be here!
                </LemonBanner>

                {hasNotifications ? (
                    notifications.map((logItem, index) => (
                        <ActivityLogRow logItem={logItem} key={index} showExtendedDescription={false} />
                    ))
                ) : (
                    <p>You're all caught up!</p>
                )}
            </div>
        </div>
    )
}
