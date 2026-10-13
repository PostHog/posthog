import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason, userHasAccess } from 'lib/utils/accessControlUtils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { FeaturePreviewSceneGate } from '~/layout/scenes/components/FeaturePreviewSceneGate'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { SessionInsights } from 'products/customer_analytics/frontend/components/Insights/SessionInsights'
import { GroupsIntroduction } from 'products/groups/frontend/components/GroupsIntroduction'

import { AccountNotesTabContent } from './components/AccountNotes/AccountNotesTabContent'
import { AccountsTabContent } from './components/Accounts/AccountsTabContent'
import { AnnouncementsTabContent } from './components/Announcements/AnnouncementsTabContent'
import { CustomerJourneys } from './components/CustomerJourneys/CustomerJourneys'
import { CustomerJourneySelect } from './components/CustomerJourneys/CustomerJourneySelect'
import { customerJourneysLogic } from './components/CustomerJourneys/customerJourneysLogic'
import { DeleteJourneyButton } from './components/CustomerJourneys/DeleteJourneyButton'
import { journeyEditorLogic } from './components/CustomerJourneys/journeyEditorLogic'
import { CustomerTasksInbox } from './components/CustomerTasks/CustomerTasksInbox'
import { FeatureRequestsTabContent } from './components/FeatureRequests/FeatureRequestsTabContent'
import { FeedTabContent } from './components/Feed/FeedTabContent'
import { FeedbackButton } from './components/FeedbackButton'
import { ActiveUsersInsights } from './components/Insights/ActiveUsersInsights'
import { SignupInsights } from './components/Insights/SignupInsights'
import { TaskDigestButton } from './components/TaskDigest/TaskDigestButton'
import { CUSTOMER_ANALYTICS_DATA_COLLECTION_NODE_ID } from './constants'
import { CustomerAnalyticsFilters } from './CustomerAnalyticsFilters'
import { customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'
import { customerAnalyticsEmptyState } from './emptyState/customerAnalyticsEmptyState'
import { customerAnalyticsFeaturePreviewGate } from './featurePreviewGate'

export const scene: SceneExport = {
    component: CustomerAnalyticsScene,
    logic: customerAnalyticsSceneLogic,
    productKey: ProductKey.CUSTOMER_ANALYTICS,
    emptyState: customerAnalyticsEmptyState,
}

export function CustomerAnalyticsScene(): JSX.Element {
    return (
        <FeaturePreviewSceneGate config={customerAnalyticsFeaturePreviewGate}>
            <CustomerAnalyticsSceneContent />
        </FeaturePreviewSceneGate>
    )
}

function CustomerAnalyticsSceneContent(): JSX.Element {
    const { addProductIntent } = useActions(teamLogic)
    const { reportCustomerAnalyticsDashboardConfigurationButtonClicked, reportCustomerAnalyticsViewed } =
        useActions(eventUsageLogic)
    const { businessType, activeTab } = useValues(customerAnalyticsSceneLogic)
    const { shouldShowGroupsIntroduction } = useValues(groupsAccessLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { location, searchParams } = useValues(router)
    const { isEditMode, stagedNodes, isSaving } = useValues(journeyEditorLogic)
    const { saveChanges, cancelChanges } = useActions(journeyEditorLogic)
    const { activeJourney } = useValues(customerJourneysLogic)

    const accessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.CustomerAnalytics,
        AccessControlLevel.Editor
    )
    const canViewAllCustomerTasks = userHasAccess(
        AccessControlResourceType.CustomerAnalytics,
        AccessControlLevel.Viewer
    )
    const canCreateCustomerTasks = userHasAccess(AccessControlResourceType.CustomerAnalytics, AccessControlLevel.Editor)

    useOnMountEffect(() => {
        reportCustomerAnalyticsViewed()
    })

    // Accounts, Notes, Announcements and Feed are gated by CUSTOMER_ANALYTICS_CSP; without it the
    // tabs do not exist, so guessed `/customer_analytics/{accounts,notes,announcements,feed}` URLs
    // are 404s.
    if (
        (activeTab === 'accounts' || activeTab === 'notes' || activeTab === 'announcements' || activeTab === 'feed') &&
        !featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]
    ) {
        return <NotFound object="page" />
    }

    if (activeTab === 'feature_requests' && !featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_FEATURE_REQUESTS]) {
        return <NotFound object="page" />
    }

    if (activeTab === 'tasks' && !featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS]) {
        return <NotFound object="page" />
    }

    const dashboardContent =
        businessType === 'b2b' && shouldShowGroupsIntroduction ? (
            <>
                <CustomerAnalyticsFilters />
                <GroupsIntroduction />
            </>
        ) : (
            <>
                <CustomerAnalyticsFilters />
                <div className="space-y-2">
                    <ActiveUsersInsights />
                    <SignupInsights />
                    <SessionInsights />
                </div>
            </>
        )

    const tabLink = (url: string, tab: string): string => {
        const params = { ...searchParams }
        if (tab !== activeTab && (tab === 'tasks' || activeTab === 'tasks')) {
            for (const key of [
                'search',
                'status',
                'assignee',
                'archive',
                'due',
                'account',
                'sort',
                'page',
                'task_id',
                'source',
            ]) {
                delete params[key]
            }
        }
        return combineUrl(url, params).url
    }
    const tabs: LemonTab<string>[] = []

    if (featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]) {
        tabs.push({
            key: 'feed',
            label: 'Feed',
            content: <FeedTabContent />,
            link: tabLink(urls.customerAnalyticsFeed(), 'feed'),
        })
        tabs.push({
            key: 'accounts',
            label: 'Accounts',
            content: <AccountsTabContent />,
            link: tabLink(urls.customerAnalyticsAccounts(), 'accounts'),
        })
        tabs.push({
            key: 'notes',
            label: 'Notes',
            content: <AccountNotesTabContent />,
            link: tabLink(urls.customerAnalyticsNotes(), 'notes'),
        })
        tabs.push({
            key: 'announcements',
            label: 'Announcements',
            content: <AnnouncementsTabContent />,
            link: tabLink(urls.customerAnalyticsAnnouncements(), 'announcements'),
        })
    }

    if (featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_FEATURE_REQUESTS]) {
        tabs.push({
            key: 'feature_requests',
            label: 'Feature requests',
            content: <FeatureRequestsTabContent />,
            link: tabLink(urls.customerAnalyticsFeatureRequests(), 'feature_requests'),
        })
    }

    if (featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS]) {
        tabs.push({
            key: 'tasks',
            label: 'Tasks',
            content: <CustomerTasksInbox canCreate={canCreateCustomerTasks} canViewAll={canViewAllCustomerTasks} />,
            link: tabLink(urls.customerAnalyticsTasks(), 'tasks'),
        })
    }

    tabs.push({
        key: 'dashboard',
        label: 'Dashboard',
        content: dashboardContent,
        link: tabLink(urls.customerAnalyticsDashboard(), 'dashboard'),
    })

    if (featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_JOURNEYS]) {
        tabs.push({
            key: 'journeys',
            label: 'Customer journeys',
            content: <CustomerJourneys />,
            link: tabLink(urls.customerAnalyticsJourneys(), 'journeys'),
        })
    }

    const tabsContent =
        tabs.length > 1 ? (
            <LemonTabs activeKey={activeTab} data-attr="customer-analytics-tabs" tabs={tabs} sceneInset />
        ) : (
            dashboardContent
        )
    const isFeatureRequestDetail =
        activeTab === 'feature_requests' && /\/customer_analytics\/feature-requests\/[^/]+\/?$/.test(location.pathname)

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: CUSTOMER_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
            <SceneContent className={isFeatureRequestDetail ? 'gap-y-0 border-b-0 flex-1 min-h-0' : undefined}>
                {isFeatureRequestDetail ? (
                    <div className="flex flex-col -mx-4 flex-1 min-h-0 overflow-auto">
                        <FeatureRequestsTabContent />
                    </div>
                ) : (
                    <>
                        <SceneTitleSection
                            name={activeTab === 'tasks' ? 'Tasks' : sceneConfigurations[Scene.CustomerAnalytics].name}
                            description={
                                activeTab === 'tasks'
                                    ? 'Work assigned to you across customer accounts.'
                                    : sceneConfigurations[Scene.CustomerAnalytics].description
                            }
                            resourceType={{
                                type: sceneConfigurations[Scene.CustomerAnalytics].iconType || 'default_icon_type',
                            }}
                            actions={
                                <>
                                    <FeedbackButton id="customer-analytics-dashboard-feedback-button" />
                                    {activeTab === 'tasks' && <TaskDigestButton />}
                                    {isEditMode ? (
                                        <div className="flex items-center gap-2">
                                            <span className="text-sm text-muted font-medium whitespace-nowrap">
                                                {stagedNodes.length} step{stagedNodes.length !== 1 ? 's' : ''} to add
                                            </span>
                                            <LemonButton type="secondary" size="small" onClick={cancelChanges}>
                                                Cancel
                                            </LemonButton>
                                            <LemonButton
                                                type="primary"
                                                size="small"
                                                onClick={saveChanges}
                                                disabledReason={
                                                    accessControlDisabledReason ??
                                                    (stagedNodes.length === 0 ? 'No steps staged' : undefined)
                                                }
                                                loading={isSaving}
                                            >
                                                Save
                                            </LemonButton>
                                        </div>
                                    ) : activeTab === 'journeys' ? (
                                        <>
                                            <CustomerJourneySelect />
                                            <LemonButton
                                                type="primary"
                                                size="small"
                                                to={urls.customerJourneyTemplates()}
                                                data-attr="new-journey"
                                                disabledReason={accessControlDisabledReason}
                                            >
                                                New journey
                                            </LemonButton>
                                            {activeJourney && (
                                                <LemonButton
                                                    type="secondary"
                                                    size="small"
                                                    to={`${urls.customerJourneyEdit(activeJourney.id)}?insightId=${activeJourney.insight}`}
                                                    data-attr="edit-journey"
                                                >
                                                    Edit
                                                </LemonButton>
                                            )}
                                            <DeleteJourneyButton />
                                        </>
                                    ) : (
                                        <Shortcut
                                            name="CustomerAnalyticsSettings"
                                            keybind={[keyBinds.settings]}
                                            intent="Configure customer analytics"
                                            interaction="click"
                                            scope={Scene.CustomerAnalytics}
                                        >
                                            <LemonButton
                                                icon={<IconGear />}
                                                size="small"
                                                type="secondary"
                                                to={
                                                    activeTab === 'accounts'
                                                        ? `${urls.customerAnalyticsConfiguration()}?tab=customer-analytics-accounts`
                                                        : urls.customerAnalyticsConfiguration()
                                                }
                                                onClick={() => {
                                                    addProductIntent({
                                                        product_type: ProductKey.CUSTOMER_ANALYTICS,
                                                        intent_context:
                                                            ProductIntentContext.CUSTOMER_ANALYTICS_DASHBOARD_CONFIGURATION_BUTTON_CLICKED,
                                                    })
                                                    reportCustomerAnalyticsDashboardConfigurationButtonClicked()
                                                }}
                                                tooltip="Configure customer analytics"
                                                children="Configure"
                                                data-attr="customer-analytics-config"
                                            />
                                        </Shortcut>
                                    )}
                                </>
                            }
                        />
                        {tabsContent}
                    </>
                )}
            </SceneContent>
        </BindLogic>
    )
}
