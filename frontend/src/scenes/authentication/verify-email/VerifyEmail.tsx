import { SceneExport } from 'scenes/sceneTypes'

import { VerifyEmailForm } from './VerifyEmailForm'
import { verifyEmailLogic } from './verifyEmailLogic'

export const scene: SceneExport = {
    component: VerifyEmail,
    logic: verifyEmailLogic,
}

export function VerifyEmail(): JSX.Element {
    return <VerifyEmailForm />
}
