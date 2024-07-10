import { IconEllipsis, IconSearch } from '@posthog/icons'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { WebAnalyticsDashboard } from 'scenes/web-analytics/WebDashboard'

export function WebAnalyticsScene(): JSX.Element {
    return (
        <>
            <PageHeader
                buttons={
                    <>
                        <LemonMenu
                            items={[
                                {
                                    label: 'Session Attribution Explorer',
                                    to: urls.sessionAttributionExplorer(),
                                    icon: <IconSearch />,
                                },
                            ]}
                        >
                            <LemonButton icon={<IconEllipsis />} size="small" />
                        </LemonMenu>
                    </>
                }
            />

            <WebAnalyticsDashboard />
        </>
    )
}

export const scene: SceneExport = {
    component: WebAnalyticsScene,
    logic: webAnalyticsLogic,
}
