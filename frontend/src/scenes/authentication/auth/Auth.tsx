import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { preflightLogic } from 'lib/logic/preflightLogic'
import { AUTH_NOTES, type AuthNotes } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene } from 'scenes/authentication/shared/authScene/AuthScene'
import { AuthEntry } from 'scenes/authentication/shared/authStepViewed'
import { useLastLoginMethod } from 'scenes/authentication/shared/lastLoginMethod'
import { loginTelemetryLogic } from 'scenes/authentication/shared/loginTelemetryLogic'
import { passkeyLogic } from 'scenes/authentication/shared/passkeyLogic'
import { pendingOAuthConnectionLogic } from 'scenes/authentication/shared/pendingOAuthConnectionLogic'
import { RedirectIfLoggedInOtherInstance } from 'scenes/authentication/shared/RedirectToLoggedInInstance'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { AuthPageStep, authLogic } from './authLogic'
import { authTelemetryLogic } from './authTelemetryLogic'
import { EmailStep } from './steps/EmailStep'
import { LoginCodeStep } from './steps/LoginCodeStep'
import { PendingInviteStep } from './steps/PendingInviteStep'
import { SignupProfileStep } from './steps/SignupProfileStep'

export const scene: SceneExport = {
    component: Auth,
    logic: authLogic,
}

function authNotes(step: AuthPageStep, entry: AuthEntry, isReturning: boolean): AuthNotes {
    switch (step) {
        case 'login':
        case 'login_code':
            return AUTH_NOTES.auth.welcomeBack
        case 'signup_credentials':
        case 'signup_pending_invite':
            return AUTH_NOTES.auth.createAccount
        case 'signup_profile':
            return AUTH_NOTES.auth.signupProfile
        default:
            if (entry === 'signup') {
                return AUTH_NOTES.auth.createAccount
            }
            return isReturning ? AUTH_NOTES.auth.welcomeBack : AUTH_NOTES.auth.firstVisit
    }
}

const STEP_COMPONENTS: Record<AuthPageStep, () => JSX.Element> = {
    // These three share one component, so React keeps the card and opens the password field inside it
    email: EmailStep,
    login: EmailStep,
    login_code: LoginCodeStep,
    signup_credentials: EmailStep,
    signup_profile: SignupProfileStep,
    signup_pending_invite: PendingInviteStep,
}

export function Auth(): JSX.Element | null {
    // Mounted here so the login funnel is only reported from the auth scenes
    useMountedLogic(loginTelemetryLogic)
    useMountedLogic(authTelemetryLogic)
    // Mounted at the scene root so the cookie is read once, not on every step change
    const { pendingConnection } = useValues(pendingOAuthConnectionLogic)
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

    const StepComponent = STEP_COMPONENTS[step]

    // A finished signup navigates away with a full page load, so nothing should render in between
    if (user) {
        return null
    }

    return (
        <AuthScene notes={authNotes(step, entry, isReturning)}>
            {/* Signup never had this redirect, and a pending OAuth connection belongs to this region */}
            {preflight?.cloud && entry === 'login' && !pendingConnection && <RedirectIfLoggedInOtherInstance />}
            <StepComponent />
        </AuthScene>
    )
}
