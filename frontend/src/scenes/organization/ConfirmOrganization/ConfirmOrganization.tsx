import { SceneExport } from 'scenes/sceneTypes'
import { organizationLogic } from 'scenes/organizationLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { useActions, useValues } from 'kea'
import { confirmOrganizationLogic } from './confirmOrganizationLogic'
import { Field } from 'lib/forms/Field'
import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { Form } from 'kea-forms'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import SignupRoleSelect from 'lib/components/SignupRoleSelect'
import SignupReferralSourceSelect from 'lib/components/SignupReferralSourceSelect'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export const scene: SceneExport = {
    component: ConfirmOrganization,
    logic: organizationLogic,
}

export function ConfirmOrganization(): JSX.Element {
    const { isConfirmOrganizationSubmitting, email, showNewOrgWarning } = useValues(confirmOrganizationLogic)
    const { setShowNewOrgWarning } = useActions(confirmOrganizationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <BridgePage view="org-creation-confirmation" hedgehog>
            <h2>Create a new organization</h2>
            <div className="flex-1">
                <p className="text-center">
                    <strong>
                        Trying to join an existing organization? <br />
                        {!showNewOrgWarning && (
                            <a
                                onClick={() => {
                                    setShowNewOrgWarning(true)
                                }}
                            >
                                Read more
                            </a>
                        )}
                    </strong>
                </p>
                <AnimatedCollapsible collapsed={!showNewOrgWarning}>
                    <div className="py-2">
                        <p>
                            If you're trying to join an existing organization, you should not create a new one. Some
                            reasons that you may accidentally end up here are:
                        </p>
                        <ul className="list-disc pl-4">
                            <li>You're logging in with the wrong email address</li>
                            <li>Your PostHog account is at a different URL</li>
                            <li>You need an invitation from a colleague</li>
                        </ul>
                    </div>
                </AnimatedCollapsible>
            </div>

            <Form
                logic={confirmOrganizationLogic}
                formKey="confirmOrganization"
                enableFormOnSubmit
                className="space-y-4"
            >
                <Field name="email" label="Email">
                    <LemonInput className="ph-ignore-input" value={email} disabled />
                </Field>

                <Field name="first_name" label="Your name">
                    <LemonInput className="ph-ignore-input" placeholder="Jane Doe" />
                </Field>

                <Field
                    name="organization_name"
                    label="Organization name"
                    help="You can always rename your organization later"
                >
                    <LemonInput className="ph-ignore-input" placeholder="Hogflix Movies" />
                </Field>

                <SignupRoleSelect />
                {featureFlags[FEATURE_FLAGS.REFERRAL_SOURCE_SELECT] === 'test' ? (
                    <SignupReferralSourceSelect />
                ) : (
                    <>
                        <Field name="referral_source" label="Where did you hear about us?" showOptional>
                            <LemonInput
                                className="ph-ignore-input"
                                data-attr="signup-referral-source"
                                placeholder=""
                                disabled={isConfirmOrganizationSubmitting}
                            />
                        </Field>
                    </>
                )}

                <LemonButton
                    htmlType="submit"
                    fullWidth
                    center
                    type="primary"
                    loading={isConfirmOrganizationSubmitting}
                >
                    Create organization
                </LemonButton>
            </Form>

            <div className="text-center terms-and-conditions-text mt-4 text-muted">
                By creating an account, you agree to our{' '}
                <a href={`https://posthog.com/terms`} target="_blank" rel="noopener">
                    Terms of Service
                </a>{' '}
                and{' '}
                <a href={`https://posthog.com/privacy`} target="_blank" rel="noopener">
                    Privacy Policy
                </a>
                .
            </div>
            <LemonDivider thick dashed className="my-6" />
            <div className="text-center terms-and-conditions-text mt-4 text-muted">
                Have questions?{' '}
                <a href={`https://posthog.com/support`} target="_blank" rel="noopener">
                    Visit support
                </a>{' '}
                or{' '}
                <a href={`https://posthog.com/docs`} target="_blank" rel="noopener">
                    read our documentation
                </a>
                .
            </div>
        </BridgePage>
    )
}
