import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect, useRef } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import PasswordStrength from 'lib/components/PasswordStrength'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import RegionSelect from 'scenes/authentication/RegionSelect'

import { signupLogic } from '../signupLogic'

export function SignupPanel1(): JSX.Element | null {
    const { preflight, socialAuthAvailable } = useValues(preflightLogic)
    const { isSignupPanel1Submitting, validatedPassword, loginUrl, emailCaseNotice } = useValues(signupLogic)
    const emailInputRef = useRef<HTMLInputElement | null>(null)

    useEffect(() => {
        // There's no password in the demo environment
        emailInputRef?.current?.focus()
    }, [preflight?.demo])

    return (
        <div className="deprecated-space-y-4 Signup__panel__1">
            <RegionSelect />
            {!preflight?.demo && socialAuthAvailable && (
                <>
                    <SocialLoginButtons caption="Sign up with" bottomDivider className="mt-6" />
                    <p className="text-secondary text-center mb-0">Or use email & password</p>
                </>
            )}
            <Form logic={signupLogic} formKey="signupPanel1" className="deprecated-space-y-4" enableFormOnSubmit>
                <LemonField
                    name="email"
                    label="Email"
                    help={emailCaseNotice && <span className="text-warning">{emailCaseNotice}</span>}
                >
                    <LemonInput
                        className="ph-ignore-input"
                        autoFocus
                        data-attr="signup-email"
                        placeholder="email@yourcompany.com"
                        type="email"
                        inputRef={emailInputRef}
                        disabled={isSignupPanel1Submitting}
                    />
                </LemonField>
                {!preflight?.demo && (
                    <LemonField
                        name="password"
                        label={
                            <div className="flex flex-1 items-center justify-between">
                                <span>Password</span>
                                <PasswordStrength validatedPassword={validatedPassword} />
                            </div>
                        }
                    >
                        <LemonInput
                            type="password"
                            autoComplete="new-password"
                            className="ph-ignore-input"
                            data-attr="password"
                            placeholder="••••••••••"
                            disabled={isSignupPanel1Submitting}
                        />
                    </LemonField>
                )}
                <LemonButton
                    fullWidth
                    type="primary"
                    status="alt"
                    center
                    htmlType="submit"
                    data-attr="signup-start"
                    loading={isSignupPanel1Submitting}
                    disabled={isSignupPanel1Submitting}
                    size="large"
                >
                    Continue
                </LemonButton>
            </Form>
            {!preflight?.demo && (preflight?.cloud || preflight?.initiated) && (
                // If we're in the demo environment, login is unified with signup and it's passwordless
                // For now, if you're not on Cloud, you wouldn't see this page,
                // but future-proofing this (with `preflight.initiated`) in case this changes
                <div className="text-center mt-4">
                    Already have an account?{' '}
                    <Link to={loginUrl} data-attr="signup-login-link" className="font-bold">
                        Log in
                    </Link>
                </div>
            )}
        </div>
    )
}
