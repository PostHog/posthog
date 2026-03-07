import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useRef } from 'react'

import { IconActivity, IconBell, IconList, IconNotification } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSkeleton, Link, Spinner } from '@posthog/lemon-ui'

import { ActivityLogRow } from 'lib/components/ActivityLog/ActivityLog'
import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { MemberSelect } from 'lib/components/MemberSelect'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { HOG_FUNCTION_SUB_TEMPLATES } from 'scenes/hog-functions/sub-templates/sub-templates'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelActivityLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelActivityLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import {
    AccessControlLevel,
    AccessControlResourceType,
    AvailableFeature,
    CyclotronJobFilterPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { SidePanelContentContainer } from '../../SidePanelContentContainer'

const SCROLL_TRIGGER_OFFSET = 100

export const SidePanelActivityIcon = ({ className }: { className?: string }): JSX.Element => {
    return <IconActivity className={className} />
}

export const SidePanelActivity = (): JSX.Element => {
    const { allActivity, allActivityResponseLoading, allActivityHasNext, activeFilters, contextFromPage } =
        useValues(sidePanelActivityLogic)
    const { maybeLoadOlderActivity, setActiveFilters } = useActions(sidePanelActivityLogic)

    const { closeSidePanel } = useActions(sidePanelStateLogic)

    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const hasAccess = userHasAccess(AccessControlResourceType.ActivityLog, AccessControlLevel.Viewer)

    const lastScrollPositionRef = useRef(0)
    const contentRef = useRef<HTMLDivElement | null>(null)

    const handleScroll = (e: React.UIEvent<HTMLDivElement>): void => {
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

    if (!hasAccess) {
        return (
            <div className="flex flex-col overflow-hidden flex-1">
                <SidePanelContentContainer>
                    <SidePanelPaneHeader title="Activity logs" />
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
                </SidePanelContentContainer>
            </div>
        )
    }

    return (
        <div className="flex flex-col overflow-hidden flex-1">
            <PayGateMini
                feature={AvailableFeature.AUDIT_LOGS}
                className="flex flex-col flex-1 overflow-hidden"
                overrideShouldShowGate={user?.is_impersonated || !!featureFlags[FEATURE_FLAGS.AUDIT_LOGS_ACCESS]}
            >
                <div className="flex flex-col flex-1 overflow-hidden" ref={contentRef} onScroll={handleScroll}>
                    <ScrollableShadows direction="vertical" innerClassName="p-2 deprecated-space-y-px">
                        <SidePanelPaneHeader title="Activity logs" />
                        {hasAnyContext ? (
                            <div className="flex items-center justify-between gap-2 pb-2">
                                <div className="flex items-center gap-2">
                                    <span>
                                        Activity on{' '}
                                        <strong>
                                            {hasItemContext
                                                ? `this ${humanizeScope(contextFromPage!.scope!, true).toLowerCase()}`
                                                : `all ${humanizeScope(contextFromPage!.scope!).toLowerCase()}`}
                                        </strong>
                                    </span>
                                    {featureFlags[FEATURE_FLAGS.CDP_ACTIVITY_LOG_NOTIFICATIONS] && (
                                        <LemonMenu
                                            placement="bottom-start"
                                            items={
                                                [
                                                    {
                                                        items: HOG_FUNCTION_SUB_TEMPLATES['activity-log'].map(
                                                            (subTemplate) => {
                                                                const properties: CyclotronJobFilterPropertyFilter[] = [
                                                                    {
                                                                        key: 'scope',
                                                                        type: PropertyFilterType.Event,
                                                                        value: contextFromPage!.scope!,
                                                                        operator: PropertyOperator.Exact,
                                                                    },
                                                                ]

                                                                if (hasItemContext) {
                                                                    properties.push({
                                                                        key: 'item_id',
                                                                        type: PropertyFilterType.Event,
                                                                        value: contextFromPage!.item_id,
                                                                        operator: PropertyOperator.Exact,
                                                                    })
                                                                }

                                                                const filters = {
                                                                    events: subTemplate.filters?.events || [],
                                                                    properties,
                                                                }

                                                                const configurationOverrides = { filters }

                                                                const configuration: Record<string, any> = {
                                                                    ...subTemplate,
                                                                    ...configurationOverrides,
                                                                }

                                                                const url = combineUrl(
                                                                    urls.hogFunctionNew(subTemplate.template_id),
                                                                    {},
                                                                    { configuration }
                                                                ).url

                                                                return {
                                                                    label: subTemplate.name || 'Subscribe',
                                                                    onClick: () => {
                                                                        closeSidePanel()
                                                                        router.actions.push(url)
                                                                    },
                                                                }
                                                            }
                                                        ),
                                                    },
                                                    {
                                                        items: [
                                                            {
                                                                label: 'View all notifications',
                                                                onClick: () => {
                                                                    closeSidePanel()
                                                                    router.actions.push(
                                                                        urls.settings(
                                                                            'environment-activity-logs',
                                                                            'activity-log-notifications'
                                                                        )
                                                                    )
                                                                },
                                                            },
                                                        ],
                                                    },
                                                ] as LemonMenuItems
                                            }
                                        >
                                            <LemonButton size="small" type="secondary" tooltip="Subscribe">
                                                <IconBell />
                                            </LemonButton>
                                        </LemonMenu>
                                    )}
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
                        {hasAnyContext ? (
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
                                                <Link
                                                    to={urls.advancedActivityLogs()}
                                                    onClick={() => closeSidePanel()}
                                                    className="text-muted-alt text-xs"
                                                >
                                                    Browse all activity logs
                                                </Link>
                                            )}
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
                                        Navigate to a page like dashboards or a specific dashboard to see activity in
                                        this panel
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
                        )}
                    </ScrollableShadows>
                </div>
            </PayGateMini>
        </div>
    )
}
