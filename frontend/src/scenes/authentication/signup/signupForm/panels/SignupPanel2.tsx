import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, Link } from '@posthog/lemon-ui'

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

    return (
        <div className="deprecated-space-y-4 Signup__panel__2">
            <Form logic={signupLogic} formKey="signupPanel2" className="deprecated-space-y-4" enableFormOnSubmit>
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
                <SignupRoleSelect />
                <SignupReferralSource disabled={isSignupPanel2Submitting} />
                <div className="divider" />

                <LemonButton
                    fullWidth
                    type="primary"
                    center
                    htmlType="submit"
                    data-attr="signup-submit"
                    onClick={() => setSignupPanel2ManualErrors({})}
                    loading={isSignupPanel2Submitting}
                    disabled={isSignupPanel2Submitting}
                    status="alt"
                    size="large"
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
