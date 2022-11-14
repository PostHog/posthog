import { useEffect, useRef, useState } from 'react'
import { Link } from 'lib/components/Link'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import { useActions, useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SIGNUP_FORM_STEPS, signupLogic } from './signupLogic'
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
    const { isSignupPanel2Submitting, signupPanel2ManualErrors, panel } = useValues(signupLogic)
    const { setPanel } = useActions(signupLogic)
    const [showSpinner, setShowSpinner] = useState(true)

    const getPreviousPanel = (panel: string): string => {
        const vals: SIGNUP_FORM_STEPS[] = Object.values(SIGNUP_FORM_STEPS)
        const currentPanelIndex: number = vals.indexOf(panel as unknown as SIGNUP_FORM_STEPS)
        const nextPanel: string = vals[currentPanelIndex - 1]
        return nextPanel
    }

    useEffect(() => {
        setShowSpinner(true)
        const t = setTimeout(() => {
            setShowSpinner(false)
        }, 500)
        return () => clearTimeout(t)
    }, [panel])

    return !user ? (
        <div className="space-y-2">
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
            {!isSignupPanel2Submitting && signupPanel2ManualErrors.generic && (
                <AlertMessage type="error">
                    {signupPanel2ManualErrors.generic?.detail || 'Could not complete your signup. Please try again.'}
                </AlertMessage>
            )}
            {panel === SIGNUP_FORM_STEPS.START ? (
                <SignupFormPanel1 />
            ) : (
                <>
                    <SignupFormPanel2 />
                    <div className="flex justify-center">
                        <LemonButton
                            type="tertiary"
                            status="muted"
                            icon={<IconArrowLeft />}
                            onClick={() => setPanel(getPreviousPanel(panel))}
                            size="small"
                            center
                        >
                            or go back
                        </LemonButton>
                    </div>
                </>
            )}
            {showSpinner ? <SpinnerOverlay /> : null}
        </div>
    ) : null
}

export function SignupFormPanel1(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { isSignupPanel1Submitting, signupPanel1 } = useValues(signupLogic)
    const emailInputRef = useRef<HTMLInputElement | null>(null)

    useEffect(() => {
        // There's no password in the demo environment
        emailInputRef?.current?.focus()
    }, [preflight?.demo])

    return (
        <div className="space-y-4 SignupForm__panel__1">
            <Form logic={signupLogic} formKey={'signupPanel1'} className="space-y-4" enableFormOnSubmit>
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

export function SignupFormPanel2(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { isSignupPanel2Submitting } = useValues(signupLogic)

    return (
        <div className="space-y-4 SignupForm__panel__2">
            <Form logic={signupLogic} formKey={'signupPanel2'} className="space-y-4" enableFormOnSubmit>
                <RegionSelect />
                <Field name="first_name" label="Your name">
                    <LemonInput
                        className="ph-ignore-input"
                        data-attr="signup-first-name"
                        placeholder="Jane Doe"
                        disabled={isSignupPanel2Submitting}
                    />
                </Field>
                <Field name="organization_name" label="Organization name">
                    <LemonInput
                        className="ph-ignore-input"
                        data-attr="signup-organization-name"
                        placeholder="Hogflix Movies"
                        disabled={isSignupPanel2Submitting}
                    />
                </Field>
                <Field name="role_at_organization" label="What is your role?">
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
                            {
                                label: 'Other',
                                value: 'other',
                            },
                        ]}
                    />
                </Field>
                <Field name="referral_source" label="Where did you hear about us?" showOptional>
                    <LemonInput
                        className="ph-ignore-input"
                        data-attr="signup-referral-source"
                        placeholder=""
                        disabled={isSignupPanel2Submitting}
                    />
                </Field>
                <div className="divider" />

                <LemonButton
                    fullWidth
                    type="primary"
                    center
                    htmlType="submit"
                    data-attr="signup-submit"
                    loading={isSignupPanel2Submitting}
                    disabled={isSignupPanel2Submitting}
                >
                    {!preflight?.demo
                        ? 'Create account'
                        : !isSignupPanel2Submitting
                        ? 'Enter the demo environment'
                        : 'Preparing demo data…'}
                </LemonButton>
            </Form>

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
