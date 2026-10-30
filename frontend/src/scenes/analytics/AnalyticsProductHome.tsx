import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { HomeDashboardMenu } from 'products/product_analytics/frontend/insights/home/HomeDashboardMenu'
import { HomeDashboardModals } from 'products/product_analytics/frontend/insights/home/HomeDashboardModals'
import { HomeTab } from 'products/product_analytics/frontend/insights/home/HomeTab'

import { AnalyticsCreateModals } from './AnalyticsCreateModals'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'

export const scene: SceneExport = {
    component: AnalyticsProductHome,
}

/** The product analytics home dashboard on its own, without the Insights tabs around it. */
export function AnalyticsProductHome(): JSX.Element {
    const railEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    if (!railEnabled) {
        return <NotFound object="page" />
    }
    return (
        <SceneContent>
            <HomeTab
                page={{
                    title: (
                        <SceneTitleSection
                            name="Product analytics"
                            description="How people use your product, ready-made by PostHog."
                            resourceType={{ type: 'analytics', forceIcon: <AnalyticsTypeIcon type="insight" /> }}
                            actions={<HomeDashboardMenu />}
                        />
                    ),
                    dashboardHeaderActions: <HomeDashboardMenu inDashboardHeader />,
                }}
            />
            <HomeDashboardModals />
            <AnalyticsCreateModals />
        </SceneContent>
    )
}
