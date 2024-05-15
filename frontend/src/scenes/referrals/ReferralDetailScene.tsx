import { useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'

import { referralProgramLogic } from './referralProgramLogic'

export const scene: SceneExport = {
    component: ReferralDetailScene,
    logic: referralProgramLogic,
    paramsToProps: ({ params: { id } }): (typeof referralProgramLogic)['props'] => ({
        id: id && id !== 'new' ? id : 'new',
    }),
}

export function ReferralDetailScene(): JSX.Element {
    const { referralProgram } = useValues(referralProgramLogic)
    return (
        <div>
            <p>Referral detail!</p>
            {referralProgram.title}
        </div>
    )
}
