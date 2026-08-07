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
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { OtherRegionHint } from 'scenes/authentication/shared/OtherRegionHint'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { confirmOrganizationLogic } from './confirmOrganizationLogic'

export const scene: SceneExport = {
    component: ConfirmOrganization,
    logic: organizationLogic,
}

function SupportFooter(): JSX.Element {
    return (
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
    )
}

// Shown when the confirm-creation page loads without an active social signup session on this origin —
// most often a stale tab reopened on the other Cloud region after signing up. The form would 400 on
// submit, so we offer a way back to login instead of a dead end.
function InactiveSessionRecovery(): JSX.Element {
    const { email } = useValues(confirmOrganizationLogic)

    return (
        <BridgePage view="org-creation-confirmation">
            <h2>Log in to finish setting up</h2>
            <p className="text-center">
                {email ? (
                    <>
                        Your signup session for <strong>{email}</strong> isn't active here.
                    </>
                ) : (
                    <>Your signup session isn't active here.</>
                )}{' '}
                Log in to pick up where you left off.
            </p>
            <OtherRegionHint />
            <LemonButton
                type="primary"
                fullWidth
                center
                to={`/login${location.search}`}
                disableClientSideRouting
                data-attr="confirm-org-inactive-session-login"
            >
                Log in
            </LemonButton>
            <LemonDivider thick dashed className="my-6" />
            <SupportFooter />
        </BridgePage>
    )
}

export function ConfirmOrganization(): JSX.Element {
    const { isConfirmOrganizationSubmitting, email, showNewOrgWarning, sessionState } =
        useValues(confirmOrganizationLogic)
    const { setShowNewOrgWarning } = useActions(confirmOrganizationLogic)

    if (sessionState === 'loading') {
        return (
            <BridgePage view="org-creation-confirmation">
                <div className="flex justify-center py-8">
                    <Spinner className="text-2xl" />
                </div>
            </BridgePage>
        )
    }

    if (sessionState === 'inactive') {
        return <InactiveSessionRecovery />
    }

    return (
        <BridgePage view="org-creation-confirmation">
            <h2>Create a new organization</h2>
            <OtherRegionHint />
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
            <SupportFooter />
        </BridgePage>
    )
}
