import { useEffect, useRef } from 'react'
import { Link } from 'lib/components/Link'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { signupControlLogic } from './signupControlLogic'
import { userLogic } from '../../../../userLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import PasswordStrength from 'lib/components/PasswordStrength'
import { AlertMessage } from 'lib/components/AlertMessage'
import RegionSelect from '../../../RegionSelect'
import SignupRoleSelect from 'lib/components/SignupRoleSelect'

export const scene: SceneExport = {
    component: SignupForm,
    logic: signupControlLogic,
}

const UTM_TAGS = 'utm_campaign=in-product&utm_tag=signup-header'

export function SignupForm(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const { isSignupSubmitting, signupManualErrors, signup } = useValues(signupControlLogic)
    const emailInputRef = useRef<HTMLInputElement | null>(null)

    useEffect(() => {
        // There's no password in the demo environment
        emailInputRef?.current?.focus()
    }, [preflight?.demo])

    return !user ? (
        <div className="space-y-2">
            <h2>{!preflight?.demo ? 'Get started' : 'Explore PostHog yourself'}</h2>
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
            <Form logic={signupControlLogic} formKey={'signup'} className="space-y-4" enableFormOnSubmit>
                <RegionSelect />
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
                <SignupRoleSelect />
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
            </Form>
            {!preflight?.demo && (
                <div>
                    <SocialLoginButtons caption="Or sign up with" topDivider />
                </div>
            )}
        </div>
    ) : null
}
