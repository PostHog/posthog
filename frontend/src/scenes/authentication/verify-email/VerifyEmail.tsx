import { SceneExport } from 'scenes/sceneTypes'

import { GlassVerifyEmail } from './variants/glass/GlassVerifyEmail'
import { verifyEmailLogic } from './verifyEmailLogic'

export const scene: SceneExport = {
    component: VerifyEmail,
    logic: verifyEmailLogic,
}

export function VerifyEmail(): JSX.Element {
    return <GlassVerifyEmail />
}
