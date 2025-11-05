import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconList, IconNotification } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTabs, Link, Spinner } from '@posthog/lemon-ui'

import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLog'
import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { MemberSelect } from 'lib/components/MemberSelect'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    SidePanelActivityTab,
    sidePanelActivityLogic,
} from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelActivityLogic'
import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { AvailableFeature } from '~/types'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { SidePanelActivityMetalytics } from './SidePanelActivityMetalytics'
import { SidePanelActivitySubscriptions } from './SidePanelActivitySubscriptions'

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
    const { activeTab, allActivity, allActivityResponseLoading, allActivityHasNext, activeFilters, contextFromPage } =
        useValues(sidePanelActivityLogic)
    const { setActiveTab, maybeLoadOlderActivity, setActiveFilters } = useActions(sidePanelActivityLogic)

    const { hasNotifications, notifications, importantChangesLoading, hasUnread } =
        useValues(sidePanelNotificationsLogic)
    const { markAllAsRead, loadImportantChanges } = useActions(sidePanelNotificationsLogic)

    const { closeSidePanel } = useActions(sidePanelStateLogic)

    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    useOnMountEffect(() => {
        loadImportantChanges(false)

        return () => {
            markAllAsRead()
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

    const hasItemContext = Boolean(contextFromPage?.scope && contextFromPage?.item_id)
    const hasListContext = Boolean(contextFromPage?.scope && !contextFromPage?.item_id)
    const hasAnyContext = hasItemContext || hasListContext

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
                                    label: 'Activity',
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
                    ) : activeTab === SidePanelActivityTab.All && hasAnyContext ? (
                        <div className="flex items-center justify-between gap-2 px-2 pb-2 deprecated-space-y-2">
                            <div>
                                Activity on{' '}
                                <strong>
                                    {hasItemContext
                                        ? `this ${humanizeScope(contextFromPage!.scope!, true).toLowerCase()}`
                                        : `all ${humanizeScope(contextFromPage!.scope!).toLowerCase()}`}{' '}
                                </strong>
                            </div>
                            <MemberSelect
                                value={activeFilters?.user ?? null}
                                onChange={(user) =>
                                    setActiveFilters({
                                        ...activeFilters,
                                        user: user?.id ?? undefined,
                                    })
                                }
                            />
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
                                hasAnyContext ? (
                                    <>
                                        {allActivityResponseLoading ? (
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
                                                <div className="flex items-center justify-center pt-1">
                                                    <Link
                                                        to={urls.advancedActivityLogs()}
                                                        onClick={() => closeSidePanel()}
                                                        className="text-muted-alt text-xs"
                                                    >
                                                        or browse all activity logs
                                                    </Link>
                                                </div>
                                            </>
                                        ) : (
                                            <div className="flex flex-col items-center gap-2 p-6 text-center border border-dashed rounded">
                                                <span>No activity yet</span>
                                                {activeFilters?.user ? (
                                                    <LemonButton
                                                        size="small"
                                                        type="secondary"
                                                        onClick={() =>
                                                            setActiveFilters({
                                                                ...activeFilters,
                                                                user: undefined,
                                                            })
                                                        }
                                                    >
                                                        Clear user filter
                                                    </LemonButton>
                                                ) : null}
                                                <div className="flex flex-col items-center justify-center text-xs text-muted-alt">
                                                    <LemonButton
                                                        size="small"
                                                        type="secondary"
                                                        to={urls.advancedActivityLogs()}
                                                        data-attr="browse-all-activity-logs"
                                                        onClick={() => closeSidePanel()}
                                                    >
                                                        Browse all activity logs
                                                    </LemonButton>
                                                </div>
                                            </div>
                                        )}
                                    </>
                                ) : (
                                    <div className="flex flex-col items-center justify-center gap-3 p-6 text-center h-full">
                                        <IconList className="text-5xl text-muted" />
                                        <div>
                                            <div className="font-semibold mb-1">Activity is context-aware</div>
                                            <div className="text-xs text-muted-alt">
                                                Navigate to a page like dashboards or a specific dashboard to see
                                                activity in this panel
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-2 text-xs text-muted-alt">
                                            <div className="border-t flex-1" />
                                            <span>or</span>
                                            <div className="border-t flex-1" />
                                        </div>
                                        <LemonButton
                                            size="small"
                                            type="secondary"
                                            to={urls.advancedActivityLogs()}
                                            data-attr="browse-all-activity-logs"
                                            onClick={() => closeSidePanel()}
                                        >
                                            Browse all activity logs
                                        </LemonButton>
                                    </div>
                                )
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
