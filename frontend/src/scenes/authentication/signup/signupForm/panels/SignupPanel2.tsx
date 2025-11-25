import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, Link } from '@posthog/lemon-ui'

import SignupCompanyTypeSelect from 'lib/components/SignupCompanyTypeSelect'
import SignupReferralSource from 'lib/components/SignupReferralSource'
import SignupRoleSelect from 'lib/components/SignupRoleSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { signupLogic } from '../signupLogic'

const UTM_TAGS = 'utm_campaign=in-product&utm_tag=signup-header'

export function SignupPanel2(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { setSignupPanel2ManualErrors } = useActions(signupLogic)
    const { isSignupPanel2Submitting } = useValues(signupLogic)

    const disabledReason = isSignupPanel2Submitting ? 'Please wait for the form to submit' : undefined

    return (
        <div className="deprecated-space-y-2 Signup__panel__2">
            <Form logic={signupLogic} formKey="signupPanel2" className="flex flex-col gap-2" enableFormOnSubmit>
                <LemonField name="name" label="Your name">
                    <LemonInput
                        className="ph-ignore-input"
                        data-attr="signup-name"
                        placeholder="Jane Doe"
                        disabled={isSignupPanel2Submitting}
                    />
                </LemonField>
                <LemonField name="organization_name" label="Organization name">
                    <LemonInput
                        className="ph-ignore-input"
                        data-attr="signup-organization-name"
                        placeholder="Hogflix Movies"
                        disabled={isSignupPanel2Submitting}
                    />
                </LemonField>

                <SignupCompanyTypeSelect disabledReason={disabledReason} />
                <SignupRoleSelect disabledReason={disabledReason} />
                <SignupReferralSource disabledReason={disabledReason} />

                <LemonButton
                    fullWidth
                    type="primary"
                    center
                    htmlType="submit"
                    data-attr="signup-submit"
                    onClick={() => setSignupPanel2ManualErrors({})}
                    loading={isSignupPanel2Submitting}
                    disabledReason={disabledReason}
                    status="alt"
                    size="large"
                    className="mt-3"
                >
                    {!preflight?.demo
                        ? 'Create account'
                        : !isSignupPanel2Submitting
                          ? 'Enter the demo environment'
                          : 'Preparing demo data…'}
                </LemonButton>
            </Form>

            <div className="text-center text-secondary">
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
