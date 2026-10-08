import { useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { loginTelemetryLogic } from 'scenes/authentication/shared/loginTelemetryLogic'
import { passkeyLogic } from 'scenes/authentication/shared/passkeyLogic'
import { pendingOAuthConnectionLogic } from 'scenes/authentication/shared/pendingOAuthConnectionLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { LoginForm } from './LoginForm'
import { loginLogic } from './loginLogic'

export const scene: SceneExport = {
    component: Login,
    logic: loginLogic,
}

export function Login(): JSX.Element {
    // Mounted here so the login funnel is only reported from the auth scenes
    useMountedLogic(loginTelemetryLogic)
    // Mounted at the scene root so the cookie is read once, not on every form state change
    useMountedLogic(pendingOAuthConnectionLogic)
    const { startConditionalPasskeyLogin } = useActions(passkeyLogic)

    // WebKit (Safari/iOS) can't open the passkey modal without a user gesture, so we show
    // passkeys via the email field's autofill instead. Other browsers keep the auto-modal.
    useEffect(() => {
        startConditionalPasskeyLogin()
    }, [startConditionalPasskeyLogin])

    return <LoginForm />
}
