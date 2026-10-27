import { useActions, useMountedLogic } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useLayoutEffect } from 'react'

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

    useLayoutEffect(() => {
        const variant = window.POSTHOG_USER_IDENTITY_WITH_FLAGS?.featureFlags?.['standalone-login-entry']
        if ((variant === 'control' || variant === 'test') && !performance.getEntriesByName('login:form-ready').length) {
            const ready = performance.mark('login:form-ready')
            posthog.capture('login form ready', {
                duration_ms: ready.startTime,
                '$feature/standalone-login-entry': variant,
            })
        }
    }, [])

    // WebKit (Safari/iOS) can't open the passkey modal without a user gesture, so we show
    // passkeys via the email field's autofill instead. Other browsers keep the auto-modal.
    useEffect(() => {
        startConditionalPasskeyLogin()
    }, [startConditionalPasskeyLogin])

    return <LoginForm />
}
