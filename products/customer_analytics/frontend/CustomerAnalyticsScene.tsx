import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { GroupsIntroduction } from 'scenes/groups/GroupsIntroduction'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { SessionInsights } from 'products/customer_analytics/frontend/components/Insights/SessionInsights'

import { CustomerAnalyticsFilters } from './CustomerAnalyticsFilters'
import { CustomerJourneys } from './components/CustomerJourneys/CustomerJourneys'
import { FeedbackBanner } from './components/FeedbackBanner'
import { ActiveUsersInsights } from './components/Insights/ActiveUsersInsights'
import { SignupInsights } from './components/Insights/SignupInsights'
import { CUSTOMER_ANALYTICS_DATA_COLLECTION_NODE_ID } from './constants'
import { customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'

export const scene: SceneExport = {
    component: CustomerAnalyticsScene,
    logic: customerAnalyticsSceneLogic,
    productKey: ProductKey.CUSTOMER_ANALYTICS,
}

export function CustomerAnalyticsScene({ tabId }: { tabId?: string }): JSX.Element {
    const { addProductIntent } = useActions(teamLogic)
    const { reportCustomerAnalyticsDashboardConfigurationButtonClicked, reportCustomerAnalyticsViewed } =
        useActions(eventUsageLogic)
    const { businessType, activeTab } = useValues(customerAnalyticsSceneLogic)
    const { shouldShowGroupsIntroduction } = useValues(groupsAccessLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { searchParams } = useValues(router)

    if (!tabId) {
        throw new Error('CustomerAnalyticsScene was rendered with no tabId')
    }

    useOnMountEffect(() => {
        reportCustomerAnalyticsViewed()
    })

    const dashboardContent =
        businessType === 'b2b' && shouldShowGroupsIntroduction ? (
            <GroupsIntroduction />
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

    const tabs: LemonTab<string>[] = [
        {
            key: 'dashboard',
            label: 'Dashboard',
            content: dashboardContent,
            link: combineUrl(urls.customerAnalyticsDashboard(), searchParams).url,
        },
    ]

    if (featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_JOURNEYS]) {
        tabs.push({
            key: 'journeys',
            label: 'Customer journeys',
            content: <CustomerJourneys />,
            link: combineUrl(urls.customerAnalyticsJourneys(), searchParams).url,
        })
    }

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: CUSTOMER_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.CustomerAnalytics].name}
                    description={sceneConfigurations[Scene.CustomerAnalytics].description}
                    resourceType={{
                        type: sceneConfigurations[Scene.CustomerAnalytics].iconType || 'default_icon_type',
                    }}
                    actions={
                        <AppShortcut
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
                                to={urls.customerAnalyticsConfiguration()}
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
                        </AppShortcut>
                    }
                />
                <FeedbackBanner feedbackButtonId="dashboard" />
                {tabs.length > 1 ? (
                    <LemonTabs activeKey={activeTab} data-attr="customer-analytics-tabs" tabs={tabs} sceneInset />
                ) : (
                    dashboardContent
                )}
            </SceneContent>
        </BindLogic>
    )
}
