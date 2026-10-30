import { useActions, useValues } from 'kea'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { RegionField } from 'scenes/authentication/shared/authScene/RegionField'

import { authLogic } from '../authLogic'
import { AuthEmailField } from '../components/AuthEmailField'
import { CreateAccountTerms } from '../components/CreateAccountTerms'
import { EmailStepSocialButtons } from '../components/EmailStepSocialButtons'
import { EmailStepSubmitButton } from '../components/EmailStepSubmitButton'
import { EmailStepTitle } from '../components/EmailStepTitle'
import { EmailTakenNotice } from '../components/EmailTakenNotice'
import { JoinOrganizationHint } from '../components/JoinOrganizationHint'
import { LoginErrorBanner } from '../components/LoginErrorBanner'
import { LoginPasswordField } from '../components/LoginPasswordField'
import { LoginSignupLink } from '../components/LoginSignupLink'
import { LoginSingleSignOnButtons } from '../components/LoginSingleSignOnButtons'
import { OtherRegionNotice } from '../components/OtherRegionNotice'
import { SessionRiskBanner } from '../components/SessionRiskBanner'
import { SignupPasswordField } from '../components/SignupPasswordField'
import { loginLogic } from '../loginLogic'
import { signupLogic } from '../signupLogic'

/**
 * The email card. It also renders the `login` and `signup_credentials` steps, so once the precheck
 * answers, the password for that path opens under the email field instead of on a new screen.
 */
export function EmailStep(): JSX.Element {
    const { login, generalError } = useValues(loginLogic)
    const { step } = useValues(authLogic)
    const { submitEmailStep } = useActions(authLogic)
    const { signupEmail } = useValues(signupLogic)

    return (
        <AuthSceneCard
            footer={step === 'signup_credentials' ? <CreateAccountTerms /> : undefined}
            showPendingConnection
        >
            <EmailStepTitle />
            <SessionRiskBanner className="mb-4" />
            <LoginErrorBanner />
            {step === 'login' && generalError?.code === 'invalid_credentials' && (
                <OtherRegionNotice email={login.email} reason="login_failed" />
            )}
            <form
                className="flex flex-col gap-4"
                noValidate
                onSubmit={(e) => {
                    e.preventDefault()
                    submitEmailStep()
                }}
            >
                <RegionField />
                <div className="flex flex-col">
                    <AuthEmailField />
                    <AnimatedCollapsible collapsed={step === 'email'} autoHeight>
                        {step === 'login' ? (
                            <LoginPasswordField />
                        ) : step === 'signup_credentials' ? (
                            <SignupPasswordField />
                        ) : (
                            <></>
                        )}
                    </AnimatedCollapsible>
                </div>
                <EmailTakenNotice />
                <EmailStepSubmitButton />
                {step === 'login' && <LoginSingleSignOnButtons />}
                {step === 'signup_credentials' && <OtherRegionNotice email={signupEmail} reason="no_account" />}
            </form>
            {step === 'login' && <LoginSignupLink />}
            <EmailStepSocialButtons />
            <JoinOrganizationHint />
        </AuthSceneCard>
    )
}
