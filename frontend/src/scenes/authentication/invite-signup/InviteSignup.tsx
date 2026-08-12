import { SceneExport } from 'scenes/sceneTypes'

import { inviteSignupLogic } from './inviteSignupLogic'
import { GlassInviteSignup } from './variants/glass/GlassInviteSignup'

export const scene: SceneExport = {
    component: InviteSignup,
    logic: inviteSignupLogic,
}

export function InviteSignup(): JSX.Element {
    return <GlassInviteSignup />
}
