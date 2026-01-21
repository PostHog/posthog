import { BindLogic, useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
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
import { FeedbackBanner } from './components/FeedbackBanner'
import { ActiveUsersInsights } from './components/Insights/ActiveUsersInsights'
import { SignupInsights } from './components/Insights/SignupInsights'
import { CUSTOMER_ANALYTICS_DATA_COLLECTION_NODE_ID } from './constants'
import { customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'

export const scene: SceneExport = {
    component: CustomerAnalyticsScene,
    logic: customerAnalyticsSceneLogic,
}

export function CustomerAnalyticsScene({ tabId }: { tabId?: string }): JSX.Element {
    const { addProductIntent } = useActions(teamLogic)
    const { reportCustomerAnalyticsDashboardConfigurationButtonClicked, reportCustomerAnalyticsViewed } =
        useActions(eventUsageLogic)
    const { businessType } = useValues(customerAnalyticsSceneLogic)
    const { shouldShowGroupsIntroduction } = useValues(groupsAccessLogic)

    if (!tabId) {
        throw new Error('CustomerAnalyticsScene was rendered with no tabId')
    }

    useOnMountEffect(() => {
        reportCustomerAnalyticsViewed()
    })

    const content =
        businessType === 'b2b' && shouldShowGroupsIntroduction ? (
            <GroupsIntroduction />
        ) : (
            <>
                <ActiveUsersInsights />
                <SignupInsights />
                <SessionInsights />
            </>
        )

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
                <CustomerAnalyticsFilters />
                <div className="space-y-2">{content}</div>
            </SceneContent>
        </BindLogic>
    )
}
