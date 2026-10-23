import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { AuthScene } from 'scenes/authentication/shared/authScene/AuthScene'
import { AuthEntry, AuthStep } from 'scenes/authentication/shared/authStepViewed'
import { useLastLoginMethod } from 'scenes/authentication/shared/lastLoginMethod'
import { loginTelemetryLogic } from 'scenes/authentication/shared/loginTelemetryLogic'
import { passkeyLogic } from 'scenes/authentication/shared/passkeyLogic'
import { pendingOAuthConnectionLogic } from 'scenes/authentication/shared/pendingOAuthConnectionLogic'
import { RedirectIfLoggedInOtherInstance } from 'scenes/authentication/shared/RedirectToLoggedInInstance'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { authLogic } from './authLogic'
import { authTelemetryLogic } from './authTelemetryLogic'
import { EmailStep } from './steps/EmailStep'
import { LoginStep } from './steps/LoginStep'
import { PendingInviteStep } from './steps/PendingInviteStep'
import { SignupCredentialsStep } from './steps/SignupCredentialsStep'
import { SignupProfileStep } from './steps/SignupProfileStep'

export const scene: SceneExport = {
    component: Auth,
    logic: authLogic,
}

function authNotes(step: AuthStep, entry: AuthEntry, isReturning: boolean): string[] {
    switch (step) {
        case 'login':
        case 'login_code':
            return ['// welcome back', '// 500,000+ teams ship here']
        case 'signup_credentials':
        case 'signup_pending_invite':
            return ['// create an account', '// 1M events free, every month']
        case 'signup_profile':
            return ['// almost there', '// last step']
        default:
            if (entry === 'signup') {
                return ['// create an account', '// 1M events free, every month']
            }
            return [isReturning ? '// welcome back' : '// hey, good to see you', '// 500,000+ teams ship here']
    }
}

export function Auth(): JSX.Element | null {
    // Mounted here so the login funnel is only reported from the auth scenes
    useMountedLogic(loginTelemetryLogic)
    useMountedLogic(authTelemetryLogic)
    // Mounted at the scene root so the cookie is read once, not on every step change
    useMountedLogic(pendingOAuthConnectionLogic)
    const { step, entry } = useValues(authLogic)
    const { user } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)
    const { startConditionalPasskeyLogin } = useActions(passkeyLogic)
    const isReturning = useLastLoginMethod() !== null

    // WebKit (Safari/iOS) can't open the passkey modal without a user gesture, so we show
    // passkeys via the email field's autofill instead. Other browsers keep the auto-modal.
    useEffect(() => {
        startConditionalPasskeyLogin()
    }, [startConditionalPasskeyLogin])

    // A finished signup navigates away with a full page load, so nothing should render in between
    if (user) {
        return null
    }

    return (
        <AuthScene notes={authNotes(step, entry, isReturning)}>
            {preflight?.cloud && <RedirectIfLoggedInOtherInstance />}
            {step === 'login' || step === 'login_code' ? (
                <LoginStep />
            ) : step === 'signup_pending_invite' ? (
                <PendingInviteStep />
            ) : step === 'signup_credentials' ? (
                <SignupCredentialsStep />
            ) : step === 'signup_profile' ? (
                <SignupProfileStep />
            ) : (
                <EmailStep />
            )}
        </AuthScene>
    )
}
