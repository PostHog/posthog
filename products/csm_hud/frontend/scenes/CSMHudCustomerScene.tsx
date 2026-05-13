import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export const scene: SceneExport = {
    component: CSMHudCustomerScene,
}

export function CSMHudCustomerScene(): JSX.Element {
    // TODO restore before merge: gate behind FEATURE_FLAGS.SCENE_CSM_HUD + is_staff + @posthog.com
    const canAccess = true

    if (!canAccess) {
        return <NotFound object="page" />
    }

    return (
        <SceneContent>
            <SceneTitleSection name="CSM HUD customer" resourceType={{ type: 'csm_hud' }} />
            <p className="text-muted">Customer drill-down placeholder.</p>
        </SceneContent>
    )
}

export default CSMHudCustomerScene
