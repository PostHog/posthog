import { SceneExport } from 'scenes/sceneTypes'

import { InviteSignupForm } from './InviteSignupForm'
import { inviteSignupLogic } from './inviteSignupLogic'

export const scene: SceneExport = {
    component: InviteSignup,
    logic: inviteSignupLogic,
}

export function InviteSignup(): JSX.Element {
    return <InviteSignupForm />
}
