import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect, useRef } from 'react'

import { LemonBanner, LemonButton, LemonInput } from '@posthog/lemon-ui'

import { SocialLoginButtons } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import RegionSelect from 'scenes/authentication/RegionSelect'

import { signupLogic } from '../signupLogic'

export function SignupPanelEmail(): JSX.Element | null {
    const { preflight, socialAuthAvailable } = useValues(preflightLogic)
    const { isSignupPanelEmailSubmitting, loginUrl, emailCaseNotice, passkeyError, error } = useValues(signupLogic)
    const emailInputRef = useRef<HTMLInputElement | null>(null)

    useEffect(() => {
        emailInputRef?.current?.focus()
    }, [])

    return (
        <div className="deprecated-space-y-4 Signup__panel__email">
            <RegionSelect />
            {passkeyError && (
                <LemonBanner type="error" className="mb-4">
                    {passkeyError}
                </LemonBanner>
            )}
            {!preflight?.demo && socialAuthAvailable && (
                <>
                    <SocialLoginButtons caption="Sign up with" bottomDivider className="mt-6" />
                    <p className="text-secondary text-center mb-0">Or use email</p>
                </>
            )}
            <Form logic={signupLogic} formKey="signupPanelEmail" className="deprecated-space-y-4" enableFormOnSubmit>
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
                    />
                </LemonField>
                {error && <LemonBanner type="error">{error}</LemonBanner>}
                <LemonButton
                    fullWidth
                    type="primary"
                    status="alt"
                    center
                    htmlType="submit"
                    data-attr="signup-start"
                    loading={isSignupPanelEmailSubmitting}
                    size="large"
                >
                    Continue
                </LemonButton>
            </Form>
            {!preflight?.demo && (preflight?.cloud || preflight?.initiated) && (
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
