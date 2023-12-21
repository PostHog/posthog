import { IconNotification } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect, LemonSkeleton, LemonTabs, Link, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLog'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { useEffect, useRef } from 'react'
import { urls } from 'scenes/urls'

import {
    sidePanelActivityLogic,
    SidePanelActivityTab,
} from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelActivityLogic'
import { ActivityScope } from '~/types'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'

const SCROLL_TRIGGER_OFFSET = 100

export const SidePanelActivityIcon = (props: { className?: string }): JSX.Element => {
    const { unreadCount } = useValues(sidePanelActivityLogic)

    return (
        <IconWithCount count={unreadCount} {...props}>
            <IconNotification />
        </IconWithCount>
    )
}

export const SidePanelActivity = (): JSX.Element => {
    const {
        hasNotifications,
        notifications,
        activeTab,
        allActivity,
        allActivityResponseLoading,
        allActivityHasNext,
        importantChangesLoading,
        hasUnread,
        filters,
    } = useValues(sidePanelActivityLogic)
    const { togglePolling, setActiveTab, maybeLoadOlderActivity, markAllAsRead, loadImportantChanges, setFilters } =
        useActions(sidePanelActivityLogic)

    usePageVisibility((pageIsVisible) => {
        togglePolling(pageIsVisible)
    })

    useEffect(() => {
        loadImportantChanges(false)
        return () => {
            markAllAsRead()
            togglePolling(false)
        }
    }, [])

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
        <div className="flex flex-col overflow-hidden flex-1">
            <SidePanelPaneHeader title="Activity" />
            <div className="flex flex-col overflow-hidden flex-1">
                <div className="shrink-0 mx-2">
                    <LemonTabs
                        inline
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

                {/* Controls */}
                <div className="shrink-0 space-y-2 p-2">
                    {activeTab === SidePanelActivityTab.Unread ? (
                        <>
                            <LemonBanner type="info">
                                Notifications shows you changes others make to{' '}
                                <Link to={urls.savedInsights('history')}>Insights</Link> and{' '}
                                <Link to={urls.featureFlags('history')}>Feature Flags</Link> that you created. Come join{' '}
                                <Link to={'https://posthog.com/community'}>our community forum</Link> and tell us what
                                else should be here!
                            </LemonBanner>

                            {hasUnread ? (
                                <div className="flex justify-end mb-2">
                                    <LemonButton type="secondary" onClick={() => markAllAsRead()}>
                                        Mark all as read
                                    </LemonButton>
                                </div>
                            ) : null}
                        </>
                    ) : activeTab === SidePanelActivityTab.All ? (
                        <div className="flex items-center justify-between gap-2">
                            <div>{allActivityResponseLoading ? <Spinner textColored /> : null}</div>

                            <div className="flex ites-center gap-2">
                                <LemonSelect
                                    size="small"
                                    options={Object.values(ActivityScope).map((x) => ({
                                        value: x,
                                        label: x,
                                    }))}
                                    placeholder="All Activity"
                                    value={filters?.scope ?? null}
                                    onChange={(value) => ({
                                        ...filters,
                                        scope: value ?? undefined,
                                        item_id: undefined,
                                    })}
                                    dropdownMatchSelectWidth={false}
                                />

                                <MemberSelect
                                    size="small"
                                    type="secondary"
                                    value={filters?.user ?? null}
                                    onChange={(user) =>
                                        setFilters({
                                            ...filters,
                                            user: user?.id ?? undefined,
                                        })
                                    }
                                />
                            </div>
                        </div>
                    ) : null}
                </div>

                <div className="flex flex-col flex-1 overflow-hidden" ref={contentRef} onScroll={handleScroll}>
                    <ScrollableShadows direction="vertical" innerClassName="p-2 space-y-x">
                        {activeTab === SidePanelActivityTab.Unread ? (
                            <>
                                {importantChangesLoading && !hasNotifications ? (
                                    <LemonSkeleton className="my-2 h-12" repeat={10} fade />
                                ) : hasNotifications ? (
                                    notifications.map((logItem, index) => (
                                        <ActivityLogRow logItem={logItem} key={index} showExtendedDescription={false} />
                                    ))
                                ) : (
                                    <div className="border rounded text-center border-dashed p-6 text-muted-alt">
                                        You're all caught up!
                                    </div>
                                )}
                            </>
                        ) : activeTab === SidePanelActivityTab.All ? (
                            <>
                                {allActivityResponseLoading && !allActivity.length ? (
                                    <LemonSkeleton className="my-2 h-12" repeat={10} fade />
                                ) : allActivity.length ? (
                                    <>
                                        {allActivity.map((logItem, index) => (
                                            <ActivityLogRow
                                                logItem={logItem}
                                                key={index}
                                                showExtendedDescription={false}
                                            />
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
                                    <div className="border rounded text-center border-dashed p-6 flex flex-col gap-2 items-center">
                                        <span>No activity yet</span>
                                        {filters ? (
                                            <LemonButton type="secondary" onClick={() => setFilters(null)}>
                                                Clear filters
                                            </LemonButton>
                                        ) : null}
                                    </div>
                                )}
                            </>
                        ) : null}
                    </ScrollableShadows>
                </div>
            </div>
        </div>
    )
}
