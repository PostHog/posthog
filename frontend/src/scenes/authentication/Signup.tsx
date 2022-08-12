import React, { useEffect, useRef } from 'react'
import { Link } from 'lib/components/Link'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { signupLogic } from './signupLogic'
import { userLogic } from '../userLogic'
import { WelcomeLogo } from './WelcomeLogo'
import { SceneExport } from 'scenes/sceneTypes'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { LemonInput } from '@posthog/lemon-ui'
import PasswordStrength from 'lib/components/PasswordStrength'
import { AlertMessage } from 'lib/components/AlertMessage'
import { AuthenticationButton } from './AuthenticationButton'

export const scene: SceneExport = {
    component: Signup,
    logic: signupLogic,
}

const UTM_TAGS = 'utm_campaign=in-product&utm_tag=signup-header'

export function Signup(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const { isSignupSubmitting, signupManualErrors, signup } = useValues(signupLogic)
    const emailInputRef = useRef<HTMLInputElement | null>(null)

    useEffect(() => {
        // There's no password in the demo environment
        emailInputRef?.current?.focus()
    }, [preflight?.demo])

    const footerHighlights = {
        cloud: ['Hosted & managed by PostHog', 'Pay per event, cancel anytime', 'Community, Slack & email support'],
        selfHosted: [
            'Fully featured product, unlimited events',
            'Data in your own infrastructure',
            'Community, Slack & email support',
        ],
    }

    return !user ? (
        <div className="BridgePage">
            <div className="AuthContent">
                <WelcomeLogo view="signup" />
                <div className="inner space-y-2">
                    <h2 className="subtitle justify-center">
                        {!preflight?.demo ? 'Get started' : 'Explore PostHog yourself'}
                    </h2>
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

                        <div className="divider" />

                        <AuthenticationButton
                            htmlType="submit"
                            data-attr="signup-submit"
                            loading={isSignupSubmitting}
                            disabled={isSignupSubmitting}
                        >
                            {'TODO' && false // submit success
                                ? 'Opening PostHog…'
                                : !preflight?.demo
                                ? 'Create account'
                                : !isSignupSubmitting
                                ? 'Enter the demo environment'
                                : 'Preparing demo data…'}
                        </AuthenticationButton>

                        <div className="text-center text-muted-alt">
                            By {!preflight?.demo ? 'creating an account' : 'entering the demo environment'}, you agree
                            to our{' '}
                            <a href={`https://posthog.com/terms?${UTM_TAGS}`} target="_blank" rel="noopener">
                                Terms of Service
                            </a>{' '}
                            and{' '}
                            <a href={`https://posthog.com/privacy?${UTM_TAGS}`} target="_blank" rel="noopener">
                                Privacy Policy
                            </a>
                            .
                        </div>
                    </Form>
                    {!preflight?.demo && (
                        <div>
                            <SocialLoginButtons caption="Or sign up with" topDivier />
                        </div>
                    )}
                </div>

                <footer>
                    {footerHighlights[preflight?.cloud ? 'cloud' : 'selfHosted'].map((val, idx) => (
                        <span key={idx} className="text-center">
                            {val}
                        </span>
                    ))}
                </footer>
            </div>
        </div>
    ) : null
}
