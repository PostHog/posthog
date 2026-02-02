import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { healthSceneLogic } from './healthSceneLogic'

export const scene: SceneExport = {
    component: HealthScene,
    logic: healthSceneLogic,
}

export function HealthScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Health"
                description="See an at-a-glance view of the health of your project."
                resourceType={{
                    to: undefined,
                    type: 'health',
                }}
                actions={
                    <LemonButton type="primary" size="small">
                        Refresh
                    </LemonButton>
                }
            />

            <LemonBanner type="info">
                <strong>DEVELOPMENT WARNING!</strong> This is being actively developed and will be updated soon.
            </LemonBanner>
        </SceneContent>
    )
}
