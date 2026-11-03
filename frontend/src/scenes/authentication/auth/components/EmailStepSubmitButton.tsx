import { useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { authLogic } from '../authLogic'
import { loginLogic } from '../loginLogic'
import { signupLogic } from '../signupLogic'

export function EmailStepSubmitButton(): JSX.Element | null {
    const { entry, step, isEmailSubmitting, isLoginPasswordHidden } = useValues(authLogic)
    const { isLoginSubmitting } = useValues(loginLogic)
    const { validatedPassword, passkeyRegistered, isSignupPanelAuthSubmitting } = useValues(signupLogic)

    if (step === 'login') {
        return isLoginPasswordHidden ? null : (
            <LemonButton
                type="primary"
                size="large"
                center
                fullWidth
                htmlType="submit"
                data-attr="password-login"
                loading={isLoginSubmitting}
            >
                Log in
            </LemonButton>
        )
    }
    if (step === 'signup_credentials') {
        return (
            <LemonButton
                type="primary"
                size="large"
                center
                fullWidth
                htmlType="submit"
                // pinned: Playwright and the signup funnel select the account creation submit by this
                data-attr="signup-auth-continue"
                loading={isSignupPanelAuthSubmitting}
                disabledReason={
                    !passkeyRegistered && validatedPassword.feedback ? validatedPassword.feedback : undefined
                }
            >
                Create account
            </LemonButton>
        )
    }
    return (
        <LemonButton
            type="primary"
            size="large"
            center
            fullWidth
            htmlType="submit"
            // pinned: `signup-start` is the signup funnel's existing first-step attribute
            data-attr={entry === 'signup' ? 'signup-start' : 'login-email-continue'}
            loading={isEmailSubmitting}
        >
            Continue
        </LemonButton>
    )
}
