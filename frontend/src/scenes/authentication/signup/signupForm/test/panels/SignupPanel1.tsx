import { useRef, useEffect } from 'react'
import { LemonInput, LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import PasswordStrength from 'lib/components/PasswordStrength'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { signupLogicTest } from '../signupLogicTest'

export function SignupPanel1(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { isSignupPanel1Submitting, signupPanel1 } = useValues(signupLogicTest)
    const emailInputRef = useRef<HTMLInputElement | null>(null)

    useEffect(() => {
        // There's no password in the demo environment
        emailInputRef?.current?.focus()
    }, [preflight?.demo])

    return (
        <div className="space-y-4 Signup__panel__1">
            <Form logic={signupLogicTest} formKey={'signupPanel1'} className="space-y-4" enableFormOnSubmit>
                <Field name="email" label="Email">
                    <LemonInput
                        className="ph-ignore-input"
                        autoFocus
                        data-attr="signup-email"
                        placeholder="email@yourcompany.com"
                        type="email"
                        ref={emailInputRef}
                        disabled={isSignupPanel1Submitting}
                    />
                </Field>
                {!preflight?.demo && (
                    <Field
                        name="password"
                        label={
                            <div className="flex flex-1 items-center justify-between">
                                <span>Password</span>
                                <span className="w-20">
                                    <PasswordStrength password={signupPanel1.password} />
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
                            disabled={isSignupPanel1Submitting}
                        />
                    </Field>
                )}
                <LemonButton
                    fullWidth
                    type="primary"
                    center
                    htmlType="submit"
                    data-attr="signup-start"
                    loading={isSignupPanel1Submitting}
                    disabled={isSignupPanel1Submitting}
                >
                    Continue
                </LemonButton>
            </Form>
            {!preflight?.demo && (
                <div>
                    <SocialLoginButtons caption="Or sign up with" topDivider />
                </div>
            )}
        </div>
    )
}
