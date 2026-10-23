import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { HomeTab } from 'products/product_analytics/frontend/insights/home/HomeTab'

import { AnalyticsCreateModals } from './AnalyticsCreateModals'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'

export const scene: SceneExport = {
    component: AnalyticsProductHome,
}

/** The product analytics home dashboard on its own, without the Insights tabs around it. */
export function AnalyticsProductHome(): JSX.Element {
    const railEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    const homeEnabled = useFeatureFlag('PRODUCT_ANALYTICS_HOME_TAB')
    if (!railEnabled || !homeEnabled) {
        return <NotFound object="page" />
    }
    return (
        <SceneContent>
            <SceneTitleSection
                name="Product analytics"
                description="How people use your product, ready-made by PostHog."
                resourceType={{ type: 'analytics', forceIcon: <AnalyticsTypeIcon type="insight" /> }}
            />
            <HomeTab />
            <AnalyticsCreateModals />
        </SceneContent>
    )
}
