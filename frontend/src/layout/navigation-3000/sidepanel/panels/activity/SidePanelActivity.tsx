import { IconNotification } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSelectOption, LemonSkeleton, LemonTabs, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLog'
import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { MemberSelect } from 'lib/components/MemberSelect'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { FEATURE_FLAGS } from 'lib/constants'
import { usePageVisibilityCb } from 'lib/hooks/usePageVisibility'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useEffect, useRef } from 'react'
import { userLogic } from 'scenes/userLogic'

import {
    sidePanelActivityLogic,
    SidePanelActivityTab,
} from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelActivityLogic'
import { ActivityScope, AvailableFeature } from '~/types'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { SidePanelActivityMetalytics } from './SidePanelActivityMetalytics'
import { SidePanelActivitySubscriptions } from './SidePanelActivitySubscriptions'
import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'

const SCROLL_TRIGGER_OFFSET = 100

export const SidePanelActivityIcon = (props: { className?: string }): JSX.Element => {
    const { unreadCount } = useValues(sidePanelNotificationsLogic)

    return (
        <IconWithCount count={unreadCount} {...props}>
            <IconNotification />
        </IconWithCount>
    )
}

export const SidePanelActivity = (): JSX.Element => {
    const { activeTab, allActivity, allActivityResponseLoading, allActivityHasNext, filters, filtersForCurrentPage } =
        useValues(sidePanelActivityLogic)
    const { setActiveTab, maybeLoadOlderActivity, setFilters } = useActions(sidePanelActivityLogic)

    const { hasNotifications, notifications, importantChangesLoading, hasUnread } =
        useValues(sidePanelNotificationsLogic)
    const { togglePolling, markAllAsRead, loadImportantChanges } = useActions(sidePanelNotificationsLogic)

    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    usePageVisibilityCb((pageIsVisible) => {
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

    const scopeMenuOptions: LemonSelectOption<ActivityScope | null>[] = [
        { value: null, label: 'All activity' },
        ...Object.values(ActivityScope).map((x) => ({
            value: x,
            label: humanizeScope(x),
        })),
    ]

    const activeScopeMenuOption = filters?.scope ? filters.scope + `${filters.item_id ?? ''}` : null

    // Add a special option for the current page context if we have one
    if (filtersForCurrentPage?.scope && filtersForCurrentPage?.item_id) {
        scopeMenuOptions.unshift({
            value: `${filtersForCurrentPage.scope}${filtersForCurrentPage.item_id ?? ''}` as any,
            label: `This ${humanizeScope(filtersForCurrentPage.scope, true)}`,
        })
    }

    return (
        <>
            <SidePanelPaneHeader title="Team activity" />
            <PayGateMini
                feature={AvailableFeature.AUDIT_LOGS}
                className="flex flex-col flex-1 overflow-hidden"
                overrideShouldShowGate={user?.is_impersonated || !!featureFlags[FEATURE_FLAGS.AUDIT_LOGS_ACCESS]}
            >
                <div className="flex flex-col flex-1 overflow-hidden">
                    <div className="mx-2 shrink-0">
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
                                ...(featureFlags[FEATURE_FLAGS.METALYTICS]
                                    ? [
                                          {
                                              key: SidePanelActivityTab.Metalytics,
                                              label: 'Analytics',
                                          },
                                      ]
                                    : []),
                                ...(featureFlags[FEATURE_FLAGS.CDP_ACTIVITY_LOG_NOTIFICATIONS]
                                    ? [
                                          {
                                              key: SidePanelActivityTab.Subscriptions,
                                              label: 'Subscriptions',
                                          },
                                      ]
                                    : []),
                            ]}
                        />
                    </div>

                    {/* Controls */}
                    {activeTab === SidePanelActivityTab.Unread ? (
                        <div className="px-2 pb-2 deprecated-space-y-2 shrink-0">
                            <div className="flex items-center justify-between gap-2">
                                {hasUnread ? (
                                    <LemonButton type="secondary" onClick={() => markAllAsRead()}>
                                        Mark all as read
                                    </LemonButton>
                                ) : null}
                            </div>
                        </div>
                    ) : activeTab === SidePanelActivityTab.All ? (
                        <div className="flex items-center justify-between gap-2 px-2 pb-2 deprecated-space-y-2 shrink-0">
                            <div className="flex items-center gap-2">
                                {allActivityResponseLoading ? <Spinner textColored /> : null}
                            </div>

                            <div className="flex items-center gap-2">
                                <span>Filter for activity on:</span>
                                <LemonSelect
                                    size="small"
                                    options={scopeMenuOptions}
                                    placeholder="All activity"
                                    value={(activeScopeMenuOption as ActivityScope) ?? undefined}
                                    onChange={(value) =>
                                        setFilters({
                                            ...filters,
                                            scope: value ?? undefined,
                                            item_id: undefined,
                                        })
                                    }
                                    dropdownMatchSelectWidth={false}
                                />

                                <span>by</span>
                                <MemberSelect
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

                    <div className="flex flex-col flex-1 overflow-hidden" ref={contentRef} onScroll={handleScroll}>
                        <ScrollableShadows direction="vertical" innerClassName="p-2 deprecated-space-y-px">
                            {activeTab === SidePanelActivityTab.Unread ? (
                                <>
                                    {importantChangesLoading && !hasNotifications ? (
                                        <LemonSkeleton className="h-12 my-2" repeat={10} fade />
                                    ) : hasNotifications ? (
                                        notifications.map((logItem, index) => (
                                            <ActivityLogRow logItem={logItem} key={index} />
                                        ))
                                    ) : (
                                        <div className="p-6 text-center border border-dashed rounded text-secondary">
                                            You're all caught up!
                                        </div>
                                    )}
                                </>
                            ) : activeTab === SidePanelActivityTab.All ? (
                                <>
                                    {allActivityResponseLoading && !allActivity.length ? (
                                        <LemonSkeleton className="h-12 my-2" repeat={10} fade />
                                    ) : allActivity.length ? (
                                        <>
                                            {allActivity.map((logItem, index) => (
                                                <ActivityLogRow logItem={logItem} key={index} />
                                            ))}

                                            <div className="flex items-center justify-center h-10 gap-2 m-4 text-secondary">
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
                                        <div className="flex flex-col items-center gap-2 p-6 text-center border border-dashed rounded">
                                            <span>No activity yet</span>
                                            {filters ? (
                                                <LemonButton type="secondary" onClick={() => setFilters(null)}>
                                                    Clear filters
                                                </LemonButton>
                                            ) : null}
                                        </div>
                                    )}
                                </>
                            ) : activeTab === SidePanelActivityTab.Metalytics ? (
                                <SidePanelActivityMetalytics />
                            ) : activeTab === SidePanelActivityTab.Subscriptions ? (
                                <SidePanelActivitySubscriptions />
                            ) : null}
                        </ScrollableShadows>
                    </div>
                </div>
            </PayGateMini>
        </>
    )
}
