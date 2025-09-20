import { IconCode2 } from '@posthog/icons'

import { PageHeader } from 'lib/components/PageHeader'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { EmbeddedAnalyticsContent } from './EmbeddedAnalyticsContent'
import { embeddedAnalyticsLogic } from './embeddedAnalyticsLogic'

export function EmbeddedAnalyticsScene({ tabId }: { tabId?: string }): JSX.Element {
    return (
        <>
            <PageHeader tabbedPage />
            <SceneContent>
                <SceneTitleSection
                    name="Embedded analytics"
                    description="Define queries your application will use via the API and monitor their cost and usage."
                    resourceType={{
                        type: 'embedded',
                        forceIcon: <IconCode2 />,
                        forceIconColorOverride: [
                            'var(--color-product-embedded-analytics-light)',
                            'var(--color-product-embedded-analytics-dark)',
                        ],
                    }}
                />
                <LemonBanner
                    type="warning"
                    dismissKey="embedded-analytics-beta-banner"
                    className="mb-2 mt-4"
                    action={{ children: 'Send feedback', id: 'embedded-analytics-feedback-button' }}
                >
                    <p>
                        Embedded analytics is in alpha and it may not be fully reliable. We are actively working on it
                        and it may change while we work with you on what works best. Please let us know what you'd like
                        to see here and/or report any issues directly to us!
                    </p>
                </LemonBanner>
                <SceneDivider />
                <EmbeddedAnalyticsContent tabId={tabId || ''} />
            </SceneContent>
        </>
    )
}

export const scene: SceneExport = {
    component: EmbeddedAnalyticsScene,
    logic: embeddedAnalyticsLogic,
}
