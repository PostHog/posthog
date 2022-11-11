import { useEffect, useRef, useState } from 'react'
import { Link } from 'lib/components/Link'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { useActions, useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SignupFormSteps, signupLogic } from './signupLogic'
import { userLogic } from '../../../../userLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import PasswordStrength from 'lib/components/PasswordStrength'
import { AlertMessage } from 'lib/components/AlertMessage'
import RegionSelect from '../../../RegionSelect'
import { IconArrowLeft } from 'lib/components/icons'
import { SpinnerOverlay } from 'lib/components/Spinner/Spinner'

export const scene: SceneExport = {
    component: SignupForm,
    logic: signupLogic,
}

const UTM_TAGS = 'utm_campaign=in-product&utm_tag=signup-header'

export function SignupForm(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const { isSignupSubmitting, signupManualErrors, panel } = useValues(signupLogic)
    const { setPanel } = useActions(signupLogic)
    const [showSpinner, setShowSpinner] = useState(true)

    useEffect(() => {
        setShowSpinner(true)
        const t = setTimeout(() => {
            setShowSpinner(false)
        }, 500)
        return () => clearTimeout(t)
    }, [panel])

    return !user ? (
        <div className="space-y-2">
            {panel !== SignupFormSteps.START ? (
                <LemonButton
                    type="tertiary"
                    icon={<IconArrowLeft />}
                    onClick={() => setPanel(SignupFormSteps.START)}
                    className="-ml-4 -mt-4 mb-4"
                >
                    Go back
                </LemonButton>
            ) : null}
            <h2>{!preflight?.demo ? panel : 'Explore PostHog yourself'}</h2>
            {!preflight?.demo && (preflight?.cloud || preflight?.initiated) && (
                // If we're in the demo environment, login is unified with signup and it's passwordless
                // For now, if you're not on Cloud, you wouldn't see this page,
                // but future-proofing this (with `preflight.initiated`) in case this changes
                <div className="text-center">
                    Already have an account?{' '}
                    <Link to="/login" data-attr="signup-login-link">
                        Log in
                    </Link>
                </div>
            )}
            {!isSignupSubmitting && signupManualErrors.generic && (
                <AlertMessage type="error">
                    {signupManualErrors.generic?.detail || 'Could not complete your signup. Please try again.'}
                </AlertMessage>
            )}
            <Form logic={signupLogic} formKey={'signup'} className="space-y-4" enableFormOnSubmit>
                {panel === SignupFormSteps.START ? <SignupFormPanel1 /> : <SignupFormPanel2 />}
                {showSpinner ? <SpinnerOverlay /> : null}
            </Form>
        </div>
    ) : null
}

export function SignupFormPanel1(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { isSignupSubmitting, signupValidationErrors, signup } = useValues(signupLogic)
    const { setPanel } = useActions(signupLogic)
    const emailInputRef = useRef<HTMLInputElement | null>(null)

    useEffect(() => {
        // There's no password in the demo environment
        emailInputRef?.current?.focus()
    }, [preflight?.demo])

    return (
        <div className="space-y-4 SignupForm__panel__1">
            <Field name="email" label="Email">
                <LemonInput
                    className="ph-ignore-input"
                    autoFocus
                    data-attr="signup-email"
                    placeholder="email@yourcompany.com"
                    type="email"
                    ref={emailInputRef}
                    disabled={isSignupSubmitting}
                />
            </Field>
            {!preflight?.demo && (
                <Field
                    name="password"
                    label={
                        <div className="flex flex-1 items-center justify-between">
                            <span>Password</span>
                            <span className="w-20">
                                <PasswordStrength password={signup.password} />
                            </span>
                        </div>
                    }
                >
                    <LemonInput
                        type="password"
                        autoComplete="new-password"
                        className="ph-ignore-input"
                        data-attr="password"
                        placeholder="••••••••••"
                        disabled={isSignupSubmitting}
                    />
                </Field>
            )}
            <LemonButton
                fullWidth
                type="primary"
                center
                data-attr="signup-start"
                onClick={() => {
                    if (!signupValidationErrors.email && !signupValidationErrors.password) {
                        setPanel(SignupFormSteps.FINISH)
                    }
                }}
            >
                Continue
            </LemonButton>
            {!preflight?.demo && (
                <div>
                    <SocialLoginButtons caption="Or sign up with" topDivider />
                </div>
            )}
        </div>
    )
}

export function SignupFormPanel2(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { isSignupSubmitting } = useValues(signupLogic)

    return (
        <div className="space-y-4 SignupForm__panel__2">
            <RegionSelect />
            <Field name="first_name" label="Your name">
                <LemonInput
                    className="ph-ignore-input"
                    data-attr="signup-first-name"
                    placeholder="Jane Doe"
                    disabled={isSignupSubmitting}
                />
            </Field>
            <Field name="organization_name" label="Organization name">
                <LemonInput
                    className="ph-ignore-input"
                    data-attr="signup-organization-name"
                    placeholder="Hogflix Movies"
                    disabled={isSignupSubmitting}
                />
            </Field>
            <Field name="role" label="What is your role?">
                <LemonSelect
                    fullWidth
                    options={[
                        {
                            label: 'Engineering',
                            value: 'engineering',
                        },
                        {
                            label: 'Product Management',
                            value: 'product',
                        },
                        {
                            label: 'Executive',
                            value: 'executive',
                        },
                        {
                            label: 'Customer Success',
                            value: 'customer-success',
                        },
                        {
                            label: 'Sales',
                            value: 'sales',
                        },
                    ]}
                />
            </Field>
            <Field name="referral_source" label="Where did you hear about us?" showOptional>
                <LemonInput
                    className="ph-ignore-input"
                    data-attr="signup-referral-source"
                    placeholder=""
                    disabled={isSignupSubmitting}
                />
            </Field>
            <div className="divider" />

            <LemonButton
                fullWidth
                type="primary"
                center
                htmlType="submit"
                data-attr="signup-submit"
                loading={isSignupSubmitting}
                disabled={isSignupSubmitting}
            >
                {!preflight?.demo
                    ? 'Create account'
                    : !isSignupSubmitting
                    ? 'Enter the demo environment'
                    : 'Preparing demo data…'}
            </LemonButton>

            <div className="text-center text-muted-alt">
                By {!preflight?.demo ? 'creating an account' : 'entering the demo environment'}, you agree to our{' '}
                <Link to={`https://posthog.com/terms?${UTM_TAGS}`} target="_blank">
                    Terms of Service
                </Link>{' '}
                and{' '}
                <Link to={`https://posthog.com/privacy?${UTM_TAGS}`} target="_blank">
                    Privacy Policy
                </Link>
                .
            </div>
        </div>
    )
}
