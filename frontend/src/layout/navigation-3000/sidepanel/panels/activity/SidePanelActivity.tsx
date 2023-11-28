import { LemonBanner, LemonButton, LemonSkeleton, LemonTabs, LemonTag, Link, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLog'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { useEffect, useRef } from 'react'
import { urls } from 'scenes/urls'

import {
    notificationsLogic,
    SidePanelActivityTab,
} from '~/layout/navigation-3000/sidepanel/panels/activity/notificationsLogic'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'

const SCROLL_TRIGGER_OFFSET = 100

export const SidePanelActivity = (): JSX.Element => {
    const {
        hasNotifications,
        notifications,
        activeTab,
        allActivity,
        allActivityResponseLoading,

        allActivityHasNext,
    } = useValues(notificationsLogic)
    const { togglePolling, setActiveTab, maybeLoadOlderActivity } = useActions(notificationsLogic)

    usePageVisibility((pageIsVisible) => {
        togglePolling(pageIsVisible)
    })

    useEffect(() => {
        return () => {
            togglePolling(false)
        }
    })
    const lastScrollPositionRef = useRef(0)
    const contentRef = useRef<HTMLDivElement | null>(null)

    const handleScroll = (e: React.UIEvent<HTMLDivElement>): void => {
        // If we are scrolling down then check if we are at the bottom of the list
        if (e.currentTarget.scrollTop > lastScrollPositionRef.current) {
            const scrollPosition = e.currentTarget.scrollTop + e.currentTarget.clientHeight
            if (e.currentTarget.scrollHeight - scrollPosition < SCROLL_TRIGGER_OFFSET) {
                maybeLoadOlderActivity()
            }
        }

        lastScrollPositionRef.current = e.currentTarget.scrollTop
    }

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
            <div className="flex flex-col overflow-hidden">
                <div className="shrink-0 mx-2 mt-2">
                    <LemonBanner type="info">
                        Notifications shows you changes others make to{' '}
                        <Link to={urls.savedInsights('history')}>Insights</Link> and{' '}
                        <Link to={urls.featureFlags('history')}>Feature Flags</Link> that you created. Come join{' '}
                        <Link to={'https://posthog.com/community'}>our community forum</Link> and tell us what else
                        should be here!
                    </LemonBanner>

                    <LemonTabs
                        activeKey={activeTab as SidePanelActivityTab}
                        onChange={(key) => setActiveTab(key)}
                        tabs={[
                            {
                                key: SidePanelActivityTab.Unread,
                                label: 'My notifications',
                            },
                            {
                                key: SidePanelActivityTab.All,
                                label: 'All activity',
                            },
                        ]}
                    />
                </div>

                <div className="flex-1 overflow-y-auto px-2">
                    {activeTab === SidePanelActivityTab.Unread ? (
                        <div className="flex-1 overflow-y-auto space-y-px">
                            {hasNotifications ? (
                                notifications.map((logItem, index) => (
                                    <ActivityLogRow logItem={logItem} key={index} showExtendedDescription={false} />
                                ))
                            ) : (
                                <p>You're all caught up!</p>
                            )}
                        </div>
                    ) : (
                        <div className="flex-1 overflow-y-auto space-y-px" ref={contentRef} onScroll={handleScroll}>
                            {allActivityResponseLoading && !allActivity.length ? (
                                <LemonSkeleton className="my-2 h-12" repeat={10} fade />
                            ) : allActivity.length ? (
                                <>
                                    {allActivity.map((logItem, index) => (
                                        <ActivityLogRow logItem={logItem} key={index} showExtendedDescription={false} />
                                    ))}

                                    <div className="m-4 h-10 flex items-center justify-center gap-2 text-muted-alt">
                                        {allActivityResponseLoading ? (
                                            <>
                                                <Spinner textColored /> Loading older activity
                                            </>
                                        ) : allActivityHasNext ? (
                                            <LemonButton
                                                type="secondary"
                                                fullWidth
                                                center
                                                onClick={() => maybeLoadOlderActivity()}
                                            >
                                                Load more
                                            </LemonButton>
                                        ) : (
                                            'No more results'
                                        )}
                                    </div>
                                </>
                            ) : (
                                <p>You're all caught up!</p>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
