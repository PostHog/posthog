import { useMountedLogic } from 'kea'

import { pendingOAuthConnectionLogic } from 'scenes/authentication/shared/pendingOAuthConnectionLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { VerifyEmailForm } from './VerifyEmailForm'
import { verifyEmailLogic } from './verifyEmailLogic'

export const scene: SceneExport = {
    component: VerifyEmail,
    logic: verifyEmailLogic,
}

export function VerifyEmail(): JSX.Element {
    // Mounted at the scene root so the cookie is read once, not on every view change
    useMountedLogic(pendingOAuthConnectionLogic)
    return <VerifyEmailForm />
}
