import { IconPieChart } from '@posthog/icons'

import { SceneExport } from 'scenes/sceneTypes'
import { WebAnalyticsDashboard } from 'scenes/web-analytics/WebAnalyticsDashboard'
import { WebAnalyticsHeaderButtons } from 'scenes/web-analytics/WebAnalyticsHeaderButtons'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export function WebAnalyticsScene(): JSX.Element {
    return (
        <>
            <SceneContent>
                <div className="flex flex-col gap-4">
                    <SceneTitleSection
                        name="Web analytics"
                        description="Analyze your web analytics data to understand website performance and user behavior."
                        resourceType={{
                            type: 'web',
                            forceIcon: <IconPieChart />,
                            forceIconColorOverride: [
                                'var(--color-product-web-analytics-light)',
                                'var(--color-product-web-analytics-dark)',
                            ],
                        }}
                        actions={<WebAnalyticsHeaderButtons />}
                    />
                    <SceneDivider />
                </div>
                <WebAnalyticsDashboard />
            </SceneContent>
        </>
    )
}

export const scene: SceneExport = {
    component: WebAnalyticsScene,
    logic: webAnalyticsLogic,
    settingSectionId: 'environment-web-analytics',
}
