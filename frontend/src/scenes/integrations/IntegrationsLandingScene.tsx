import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { integrationsLandingSceneLogic } from './integrationsLandingSceneLogic'

export const scene: SceneExport = {
    component: IntegrationsLandingScene,
    logic: integrationsLandingSceneLogic,
}

export function IntegrationsLandingScene(): JSX.Element {
    const { integration } = useValues(integrationsLandingSceneLogic)

    if (!integration) {
        return (
            <NotFound
                object="integration"
                caption="This integration doesn't exist or isn't available for a landing page."
            />
        )
    }

    return <integration.FullPage />
}

export default IntegrationsLandingScene
