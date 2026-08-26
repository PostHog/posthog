import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { Link } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import SignupReferralSource from 'lib/components/SignupReferralSource'
import SignupRoleSelect from 'lib/components/SignupRoleSelect'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { OtherRegionHint } from 'scenes/authentication/shared/OtherRegionHint'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { confirmOrganizationLogic } from './confirmOrganizationLogic'

export const scene: SceneExport = {
    component: ConfirmOrganization,
    logic: organizationLogic,
}

export function ConfirmOrganization(): JSX.Element {
    const { isConfirmOrganizationSubmitting, email, pendingInvite } = useValues(confirmOrganizationLogic)
    const { signInWithDifferentAccount } = useActions(confirmOrganizationLogic)

    return (
        <BridgePage view="org-creation-confirmation">
            <h2>Create a new organization</h2>
            <OtherRegionHint />
            <LemonBanner type="warning" className="mb-4">
                <p className="font-semibold mb-1">You are signed in as {email || 'this account'}.</p>
                {pendingInvite ? (
                    <p className="mb-2">
                        This email has a pending invite to {pendingInvite.organization_name}. Open your invite email to
                        join it instead of creating a new organization.
                    </p>
                ) : (
                    <p className="mb-2">
                        To join an existing organization, do not create a new one here. You may have signed in with the
                        wrong email, your team may use a different PostHog URL, or you may need an invite from a
                        colleague.
                    </p>
                )}
                <LemonButton
                    type="secondary"
                    onClick={signInWithDifferentAccount}
                    data-attr="confirm-organization-different-account"
                >
                    Sign in with a different account
                </LemonButton>
            </LemonBanner>

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
                <Link to="https://posthog.com/support" target="_blank" disableDocsPanel>
                    Visit support
                </Link>{' '}
                or{' '}
                <Link to="https://posthog.com/docs" target="_blank" disableDocsPanel>
                    read our documentation
                </Link>
                .
            </div>
        </BridgePage>
    )
}
