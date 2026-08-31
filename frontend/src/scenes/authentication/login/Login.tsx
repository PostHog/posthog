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

    // Start conditional UI so browsers can offer a passkey from the email field, like Google login.
    useEffect(() => {
        startConditionalPasskeyLogin()
    }, [startConditionalPasskeyLogin])

    return <LoginForm />
}
