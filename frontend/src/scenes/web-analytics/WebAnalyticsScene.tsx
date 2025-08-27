import { IconPieChart } from '@posthog/icons'

import { PageHeader } from 'lib/components/PageHeader'
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
            <PageHeader buttons={<WebAnalyticsHeaderButtons />} />
            <SceneContent>
                <SceneTitleSection
                    name="Web Analytics"
                    description="Analyze and understand your web analytics data to understand your website performance and user behavior."
                    resourceType={{
                        type: 'web',
                        typePlural: 'Web Analytics',
                        forceIcon: <IconPieChart />,
                        forceIconColorOverride: [
                            'var(--color-product-web-analytics-light)',
                            'var(--color-product-web-analytics-dark)',
                        ],
                    }}
                />
                <SceneDivider />
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
