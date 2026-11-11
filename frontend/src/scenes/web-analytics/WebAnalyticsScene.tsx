import { useValues } from 'kea'

import { useMaxTool } from 'scenes/max/useMaxTool'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { FocusModeModal } from 'scenes/web-analytics/focus-mode/FocusModeModal'
import { FocusModeOnboardingModal } from 'scenes/web-analytics/focus-mode/FocusModeOnboardingModal'
import { WebAnalyticsDashboard } from 'scenes/web-analytics/WebAnalyticsDashboard'
import { WebAnalyticsHeaderButtons } from 'scenes/web-analytics/WebAnalyticsHeaderButtons'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { WebAnalyticsSceneMenuBar } from 'scenes/web-analytics/WebAnalyticsSceneMenuBar'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

export function WebAnalyticsScene(): JSX.Element {
    useMaxTool({
        identifier: 'web_analytics_doctor',
        active: true,
        context: {},
        suggestions: [
            'Is my web analytics set up correctly?',
            'Why are my pageviews low?',
            'Diagnose my reverse proxy setup',
        ],
    })
    useMaxTool({
        identifier: 'assess_heatmap',
        active: true,
        context: {},
        suggestions: [
            'Assess the heatmap for my pricing page',
            'Why are people not clicking my main CTA?',
            'Where do users rage-click on my homepage?',
        ],
    })
    useMaxTool({
        identifier: 'summarize_website_interactions',
        active: true,
        context: {},
        suggestions: [
            'Summarize how users interact with my pricing page',
            'What are visitors doing on my homepage, and why?',
            'How do users experience my signup page?',
        ],
    })
    const { showFocusMode } = useValues(webAnalyticsLogic)

    return (
        <>
            <SceneContent>
                <WebAnalyticsSceneMenuBar />
                <SceneTitleSection
                    name={sceneConfigurations[Scene.WebAnalytics].name}
                    description={sceneConfigurations[Scene.WebAnalytics].description}
                    resourceType={{
                        type: sceneConfigurations[Scene.WebAnalytics].iconType || 'default_icon_type',
                    }}
                    actions={<WebAnalyticsHeaderButtons />}
                />
                <WebAnalyticsDashboard />
            </SceneContent>
            {showFocusMode && (
                <>
                    <FocusModeModal />
                    <FocusModeOnboardingModal />
                </>
            )}
        </>
    )
}

export const scene: SceneExport = {
    component: WebAnalyticsScene,
    logic: webAnalyticsLogic,
    productKey: ProductKey.WEB_ANALYTICS,
}
