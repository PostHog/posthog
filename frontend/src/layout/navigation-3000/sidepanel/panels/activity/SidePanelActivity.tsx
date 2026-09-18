import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconList, IconNotification } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTabs, Link, Spinner } from '@posthog/lemon-ui'

import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLogRow'
import { ActivityLogSubscribeMenu } from 'lib/components/ActivityLog/ActivityLogSubscribeMenu'
import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { MemberSelect } from 'lib/components/MemberSelect'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    ActivityFilters,
    SidePanelActivityTab,
    sidePanelActivityLogic,
} from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelActivityLogic'
import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import {
    AccessControlLevel,
    AccessControlResourceType,
    AvailableFeature,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { SidePanelActivityMetalytics } from './SidePanelActivityMetalytics'

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
    const { activeTab, contextFromPage } = useValues(sidePanelActivityLogic)
    const { setActiveTab } = useActions(sidePanelActivityLogic)

    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const hasAccess = userHasAccess(AccessControlResourceType.ActivityLog, AccessControlLevel.Viewer)

    const lastScrollPositionRef = useRef(0)

    const handleScroll = useLoadOlderActivityOnScroll(lastScrollPositionRef)

    if (!hasAccess) {
        return <AccessDeniedPane />
    }

    return (
        <>
            <SidePanelPaneHeader title="Team activity" />
            <PayGateMini
                feature={AvailableFeature.AUDIT_LOGS}
                featureDetail="activity-log-side-panel"
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
                            ]}
                        />
                    </div>

                    {/* Controls */}
                    {activeTab === SidePanelActivityTab.All && Boolean(contextFromPage?.scope) ? (
                        <ActivityContextControls
                            contextFromPage={contextFromPage!}
                            hasItemContext={Boolean(contextFromPage?.item_id)}
                        />
                    ) : null}

                    <div className="flex flex-col flex-1 overflow-hidden" onScroll={handleScroll}>
                        <ScrollableShadows direction="vertical" innerClassName="p-2 deprecated-space-y-px">
                            <ActivityPanelBody activeTab={activeTab} />
                        </ScrollableShadows>
                    </div>
                </div>
            </PayGateMini>
        </>
    )
}

function useLoadOlderActivityOnScroll(
    lastScrollPositionRef: React.MutableRefObject<number>
): (e: React.UIEvent<HTMLDivElement>) => void {
    const { maybeLoadOlderActivity } = useActions(sidePanelActivityLogic)

    return (e) => {
        // If we are scrolling down then check if we are at the bottom of the list
        if (e.currentTarget.scrollTop > lastScrollPositionRef.current) {
            const scrollPosition = e.currentTarget.scrollTop + e.currentTarget.clientHeight
            if (e.currentTarget.scrollHeight - scrollPosition < SCROLL_TRIGGER_OFFSET) {
                maybeLoadOlderActivity()
            }
        }

        lastScrollPositionRef.current = e.currentTarget.scrollTop
    }
}

function AccessDeniedPane(): JSX.Element {
    return (
        <>
            <SidePanelPaneHeader title="Team activity" />
            <div className="flex flex-col items-center justify-center gap-3 p-6 text-center h-full">
                <IconNotification className="text-5xl text-muted" />
                <div>
                    <div className="font-semibold mb-1">Access denied</div>
                    <div className="text-xs text-muted-alt">
                        You don't have sufficient permissions to view activity logs. Please contact your project
                        administrator.
                    </div>
                </div>
            </div>
        </>
    )
}

function ActivityContextControls({
    contextFromPage,
    hasItemContext,
}: {
    contextFromPage: ActivityFilters
    hasItemContext: boolean
}): JSX.Element {
    const { activeFilters } = useValues(sidePanelActivityLogic)
    const { setActiveFilters } = useActions(sidePanelActivityLogic)
    const { closeSidePanel } = useActions(sidePanelStateLogic)

    return (
        <div className="flex items-center justify-between gap-2 px-2 pb-2">
            <div className="flex items-center gap-2">
                <span>
                    Activity on{' '}
                    <strong>
                        {hasItemContext
                            ? `this ${humanizeScope(contextFromPage.scope!, true).toLowerCase()}`
                            : `all ${humanizeScope(contextFromPage.scope!).toLowerCase()}`}
                    </strong>
                </span>
                <ActivityLogSubscribeMenu
                    properties={[
                        {
                            key: 'scope',
                            type: PropertyFilterType.Event,
                            value: contextFromPage.scope!,
                            operator: PropertyOperator.Exact,
                        },
                        ...(hasItemContext
                            ? [
                                  {
                                      key: 'item_id',
                                      type: PropertyFilterType.Event as const,
                                      value: contextFromPage.item_id,
                                      operator: PropertyOperator.Exact,
                                  },
                              ]
                            : []),
                    ]}
                    onNavigate={closeSidePanel}
                    iconOnly
                />
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
    )
}

function BrowseAllActivityLogs({ onClick }: { onClick: () => void }): JSX.Element {
    return (
        <LemonButton
            size="small"
            type="secondary"
            to={urls.advancedActivityLogs()}
            data-attr="browse-all-activity-logs"
            onClick={onClick}
        >
            Browse all activity logs
        </LemonButton>
    )
}

function NoActivityYet({ activeFilters }: { activeFilters: ActivityFilters | null }): JSX.Element {
    const { setActiveFilters } = useActions(sidePanelActivityLogic)
    const { closeSidePanel } = useActions(sidePanelStateLogic)

    return (
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
                <BrowseAllActivityLogs onClick={closeSidePanel} />
            </div>
        </div>
    )
}

function NoPageContext(): JSX.Element {
    const { closeSidePanel } = useActions(sidePanelStateLogic)

    return (
        <div className="flex flex-col items-center justify-center gap-3 p-6 text-center h-full">
            <IconList className="text-5xl text-muted" />
            <div>
                <div className="font-semibold mb-1">Activity is context-aware</div>
                <div className="text-xs text-muted-alt">
                    Navigate to a page like dashboards or a specific dashboard to see activity in this panel
                </div>
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-alt">
                <div className="border-t flex-1" />
                <span>or</span>
                <div className="border-t flex-1" />
            </div>
            <BrowseAllActivityLogs onClick={closeSidePanel} />
        </div>
    )
}

function ActivityListFooter({ closeSidePanel }: { closeSidePanel: () => void }): JSX.Element {
    return (
        <div className="flex items-center justify-center pt-1">
            <Link to={urls.advancedActivityLogs()} onClick={closeSidePanel} className="text-muted-alt text-xs">
                or browse all activity logs
            </Link>
        </div>
    )
}

function ActivityList(): JSX.Element {
    const { allActivity, allActivityResponseLoading, allActivityHasNext, activeFilters } =
        useValues(sidePanelActivityLogic)
    const { maybeLoadOlderActivity } = useActions(sidePanelActivityLogic)
    const { closeSidePanel } = useActions(sidePanelStateLogic)

    if (allActivityResponseLoading) {
        return <LemonSkeleton className="h-12 my-2" repeat={10} fade />
    }

    if (!allActivity.length) {
        return <NoActivityYet activeFilters={activeFilters} />
    }

    return (
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
                    <LemonButton type="secondary" fullWidth center onClick={() => maybeLoadOlderActivity()}>
                        Load more
                    </LemonButton>
                ) : (
                    'No more results'
                )}
            </div>
            <ActivityListFooter closeSidePanel={closeSidePanel} />
        </>
    )
}

function ActivityPanelBody({ activeTab }: { activeTab: SidePanelActivityTab }): JSX.Element | null {
    const { contextFromPage } = useValues(sidePanelActivityLogic)

    const hasItemContext = Boolean(contextFromPage?.scope && contextFromPage?.item_id)
    const hasListContext = Boolean(contextFromPage?.scope && !contextFromPage?.item_id)
    const hasAnyContext = hasItemContext || hasListContext

    if (activeTab === SidePanelActivityTab.Metalytics) {
        return <SidePanelActivityMetalytics />
    }
    if (activeTab !== SidePanelActivityTab.All) {
        return null
    }
    return hasAnyContext ? <ActivityList /> : <NoPageContext />
}
