import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export const scene: SceneExport = {
    component: CSMHudCustomerScene,
}

export function CSMHudCustomerScene(): JSX.Element {
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const canAccess =
        !!featureFlags[FEATURE_FLAGS.SCENE_CSM_HUD] && !!user?.is_staff && !!user?.email?.endsWith('@posthog.com')

    if (!canAccess) {
        return <NotFound object="page" />
    }

    return (
        <SceneContent>
            <SceneTitleSection name="CSM HUD customer" />
            <p className="text-muted">Customer drill-down placeholder.</p>
        </SceneContent>
    )
}

export default CSMHudCustomerScene
