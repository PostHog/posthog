import { IconCode2 } from '@posthog/icons'

import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { EmbeddedAnalyticsContent } from './EmbeddedAnalyticsContent'
import { embeddedAnalyticsLogic } from './embeddedAnalyticsLogic'

export function EmbeddedAnalyticsScene(): JSX.Element {
    return (
        <>
            <PageHeader />
            <SceneContent>
                <SceneTitleSection
                    name="Embedded analytics"
                    description="Monitor API usage metrics and system performance through embedded analytics dashboard."
                    resourceType={{
                        type: 'embedded',
                        forceIcon: <IconCode2 />,
                        forceIconColorOverride: [
                            'var(--color-product-embedded-analytics-light)',
                            'var(--color-product-embedded-analytics-dark)',
                        ],
                    }}
                />
                <SceneDivider />
                <EmbeddedAnalyticsContent />
            </SceneContent>
        </>
    )
}

export const scene: SceneExport = {
    component: EmbeddedAnalyticsScene,
    logic: embeddedAnalyticsLogic,
}
