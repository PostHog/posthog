import { IconRocket } from '@posthog/icons'

import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { StreamlitDashboard } from './StreamlitDashboard'
import { streamlitLogic } from './streamlitLogic'

export function StreamlitScene(): JSX.Element {
    return (
        <>
            <PageHeader />
            <SceneContent>
                <SceneTitleSection
                    name="Streamlit"
                    description="Your Streamlit dashboard - ready for customization."
                    resourceType={{
                        type: 'streamlit',
                        forceIcon: <IconRocket />,
                        forceIconColorOverride: [
                            'var(--color-product-streamlit-light)',
                            'var(--color-product-streamlit-dark)',
                        ],
                    }}
                />
                <SceneDivider />
                <StreamlitDashboard />
            </SceneContent>
        </>
    )
}

export const scene: SceneExport = {
    component: StreamlitScene,
    logic: streamlitLogic,
}
