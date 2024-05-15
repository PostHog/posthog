import { SceneExport } from 'scenes/sceneTypes'

import { referralsSceneLogic } from './referralsSceneLogic'

export const scene: SceneExport = {
    component: ReferralsScene,
    logic: referralsSceneLogic,
}

export function ReferralsScene(): JSX.Element {
    return (
        <div>
            <p>Referrals!</p>
        </div>
    )
}
