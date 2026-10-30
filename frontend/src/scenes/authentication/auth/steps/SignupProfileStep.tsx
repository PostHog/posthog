import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import SignupReferralSource from 'lib/components/SignupReferralSource'
import SignupRoleSelect from 'lib/components/SignupRoleSelect'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { TurnstileChallenge } from 'scenes/authentication/shared/TurnstileChallenge'

import { signupLogic } from '../signupLogic'

export function SignupProfileStep(): JSX.Element {
    const {
        isSignupPanelOnboardingSubmitting,
        signupPanelOnboardingManualErrors,
        challengeRequired,
        turnstileSiteKey,
        turnstileToken,
        signupEmail,
    } = useValues(signupLogic)
    const { preflight } = useValues(preflightLogic)
    const { setTurnstileToken, setPanel } = useActions(signupLogic)
    const { openSupportForm } = useActions(supportLogic)

    const submitLabel = !preflight?.demo
        ? 'Create account'
        : !isSignupPanelOnboardingSubmitting
          ? 'Enter the demo environment'
          : 'Preparing demo data…'

    const footer = (
        <>
            <p className="AuthScene__terms mt-5 mb-0 text-xs leading-relaxed text-tertiary text-center">
                <span>
                    By {preflight?.demo ? 'entering the demo environment' : 'creating an account'}, you agree to our
                </span>{' '}
                <Link to="https://posthog.com/terms" target="_blank">
                    Terms of Service ↗
                </Link>{' '}
                <span>and</span>{' '}
                <Link to="https://posthog.com/privacy" target="_blank">
                    Privacy Policy ↗
                </Link>
                <span>.</span>
            </p>
            {!preflight?.demo && (
                <p className="mt-5 mb-0 text-sm text-secondary text-center">
                    <Link
                        onClick={() => setPanel(1)}
                        className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                    >
                        ← or go back
                    </Link>
                </p>
            )}
        </>
    )

    return (
        <AuthSceneCard footer={footer} showPendingConnection>
            <AuthCardTitle
                title="Tell us about yourself"
                sub={
                    <span>
                        <span>Setting up the account for</span> <span className="AuthScene__mono">{signupEmail}</span>
                    </span>
                }
            />
            {signupPanelOnboardingManualErrors?.generic && (
                <AuthBanner variant="danger" className="mb-4">
                    <span>{signupPanelOnboardingManualErrors.generic.detail || 'Could not complete your signup.'}</span>
                    {preflight?.cloud && (
                        <>
                            {' '}
                            <Link
                                // The login banner uses `login-error-contact-support`. A shared
                                // attribute would mix both pages into one autocapture funnel arm.
                                data-attr="signup-error-contact-support"
                                onClick={(e) => {
                                    e.preventDefault()
                                    openSupportForm({
                                        kind: 'support',
                                        email: signupEmail,
                                    })
                                }}
                                className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                            >
                                Contact us
                            </Link>{' '}
                            <span>to resolve this.</span>
                        </>
                    )}
                </AuthBanner>
            )}
            <Form
                logic={signupLogic}
                formKey="signupPanelOnboarding"
                enableFormOnSubmit
                className="flex flex-col gap-4"
            >
                <LemonField name="name" label="Your name">
                    {({ value, onChange, error, id }) => (
                        <LemonInput
                            id={id}
                            className="ph-ignore-input"
                            data-attr="signup-name"
                            autoFocus
                            placeholder="Jane Doe"
                            autoComplete="name"
                            value={value ?? ''}
                            onChange={onChange}
                            status={error ? 'danger' : 'default'}
                            fullWidth
                        />
                    )}
                </LemonField>
                <LemonField name="organization_name" label="Organization name">
                    {({ value, onChange, error, id }) => (
                        <LemonInput
                            id={id}
                            className="ph-ignore-input"
                            data-attr="signup-organization-name"
                            placeholder="Hogflix Movies"
                            value={value ?? ''}
                            onChange={onChange}
                            status={error ? 'danger' : 'default'}
                            fullWidth
                        />
                    )}
                </LemonField>
                <SignupRoleSelect />
                <SignupReferralSource disabled={isSignupPanelOnboardingSubmitting} />
                {challengeRequired && turnstileSiteKey ? (
                    <TurnstileChallenge
                        siteKey={turnstileSiteKey}
                        onSuccess={setTurnstileToken}
                        tokenReceived={!!turnstileToken}
                        email={signupEmail}
                    />
                ) : (
                    <LemonButton
                        type="primary"
                        size="large"
                        center
                        fullWidth
                        htmlType="submit"
                        data-attr="signup-submit"
                        loading={isSignupPanelOnboardingSubmitting}
                    >
                        {submitLabel}
                    </LemonButton>
                )}
            </Form>
        </AuthSceneCard>
    )
}
