import { useActions } from 'kea'
import { useEffect } from 'react'

import { passkeyLogic } from 'scenes/authentication/shared/passkeyLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { LoginForm } from './LoginForm'
import { loginLogic } from './loginLogic'

export const scene: SceneExport = {
    component: Login,
    logic: loginLogic,
}

export function Login(): JSX.Element {
    const { startConditionalPasskeyLogin } = useActions(passkeyLogic)

    // WebKit (Safari/iOS) can't open the passkey modal without a user gesture, so we show
    // passkeys via the email field's autofill instead. Other browsers keep the auto-modal.
    useEffect(() => {
        startConditionalPasskeyLogin()
    }, [startConditionalPasskeyLogin])

    return <LoginForm />
}
