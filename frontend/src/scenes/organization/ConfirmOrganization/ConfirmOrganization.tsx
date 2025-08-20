import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { Link } from '@posthog/lemon-ui'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import SignupReferralSource from 'lib/components/SignupReferralSource'
import SignupRoleSelect from 'lib/components/SignupRoleSelect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { confirmOrganizationLogic } from './confirmOrganizationLogic'

export const scene: SceneExport = {
    component: ConfirmOrganization,
    logic: organizationLogic,
}

export function ConfirmOrganization(): JSX.Element {
    const { isConfirmOrganizationSubmitting, email, showNewOrgWarning } = useValues(confirmOrganizationLogic)
    const { setShowNewOrgWarning } = useActions(confirmOrganizationLogic)

    return (
        <BridgePage view="org-creation-confirmation" hedgehog>
            <h2>Create a new organization</h2>
            <div className="flex-1">
                <p className="text-center">
                    <strong>
                        Trying to join an existing organization? <br />
                        {!showNewOrgWarning && (
                            <Link
                                onClick={() => {
                                    setShowNewOrgWarning(true)
                                }}
                            >
                                Read more
                            </Link>
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
                className="deprecated-space-y-4"
            >
                <LemonField name="email" label="Email">
                    <LemonInput className="ph-ignore-input" value={email} disabled />
                </LemonField>

                <LemonField name="first_name" label="Your name">
                    <LemonInput className="ph-ignore-input" placeholder="Jane Doe" />
                </LemonField>

                <LemonField
                    name="organization_name"
                    label="Organization name"
                    help="You can always rename your organization later"
                >
                    <LemonInput className="ph-ignore-input" placeholder="Hogflix Movies" />
                </LemonField>

                <SignupRoleSelect />
                <SignupReferralSource disabled={isConfirmOrganizationSubmitting} />

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

            <div className="text-center terms-and-conditions-text mt-4 text-secondary">
                By creating an account, you agree to our{' '}
                <Link to="https://posthog.com/terms" target="_blank">
                    Terms of Service
                </Link>{' '}
                and{' '}
                <Link to="https://posthog.com/privacy" target="_blank">
                    Privacy Policy
                </Link>
                .
            </div>
            <LemonDivider thick dashed className="my-6" />
            <div className="text-center terms-and-conditions-text mt-4 text-secondary">
                Have questions?{' '}
                <Link to="https://posthog.com/support" target="_blank">
                    Visit support
                </Link>{' '}
                or{' '}
                <Link to="https://posthog.com/docs" target="_blank">
                    read our documentation
                </Link>
                .
            </div>
        </BridgePage>
    )
}
