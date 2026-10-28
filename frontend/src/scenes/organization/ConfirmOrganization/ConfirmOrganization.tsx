import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { Link } from '@posthog/lemon-ui'

import SignupReferralSource from 'lib/components/SignupReferralSource'
import SignupRoleSelect from 'lib/components/SignupRoleSelect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { OtherRegionNotice } from 'scenes/authentication/auth/components/OtherRegionNotice'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
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

    const footer = (
        <>
            <p className="AuthScene__terms mt-5 mb-0 text-xs leading-relaxed text-tertiary text-center">
                <span>By creating an account, you agree to our</span>{' '}
                <Link to="https://posthog.com/terms" target="_blank">
                    Terms of Service
                </Link>{' '}
                <span>and</span>{' '}
                <Link to="https://posthog.com/privacy" target="_blank">
                    Privacy Policy
                </Link>
                <span>.</span>
            </p>
            <p className="AuthScene__terms mt-2 mb-0 text-xs leading-relaxed text-tertiary text-center">
                <span>Have questions?</span>{' '}
                <Link to="https://posthog.com/support" target="_blank">
                    Visit support
                </Link>{' '}
                <span>or</span>{' '}
                <Link to="https://posthog.com/docs" target="_blank">
                    read our documentation
                </Link>
                <span>.</span>
            </p>
        </>
    )

    return (
        <AuthScene notes={AUTH_NOTES.confirmOrganization.default}>
            <AuthSceneCard footer={footer} showPendingConnection>
                <AuthCardTitle title="Create a new organization" sub="Your own corner of PostHog." />
                <Form
                    logic={confirmOrganizationLogic}
                    formKey="confirmOrganization"
                    enableFormOnSubmit
                    className="flex flex-col gap-4"
                >
                    <LemonField name="email" label="Email">
                        <LemonInput className="ph-ignore-input" value={email} disabled fullWidth />
                    </LemonField>

                    <LemonField name="first_name" label="Your name">
                        <LemonInput className="ph-ignore-input" placeholder="Jane Doe" fullWidth />
                    </LemonField>

                    <LemonField
                        name="organization_name"
                        label="Organization name"
                        help="You can always rename your organization later"
                    >
                        <LemonInput className="ph-ignore-input" placeholder="Hogflix Movies" fullWidth />
                    </LemonField>

                    <SignupRoleSelect />
                    <SignupReferralSource disabled={isConfirmOrganizationSubmitting} />

                    <LemonButton
                        htmlType="submit"
                        fullWidth
                        center
                        size="large"
                        type="primary"
                        loading={isConfirmOrganizationSubmitting}
                    >
                        Create organization
                    </LemonButton>
                    {email && <OtherRegionNotice email={email} reason="no_account" />}
                </Form>
                <div className="mt-4 text-center">
                    <button
                        type="button"
                        data-attr="confirm-organization-join-existing"
                        className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-secondary text-xs"
                        onClick={() => setShowNewOrgWarning(!showNewOrgWarning)}
                    >
                        Trying to join an existing organization?
                    </button>
                    {showNewOrgWarning && (
                        <AuthBanner variant="note" className="mt-3">
                            <p className="m-0 mb-1.5">
                                If you're trying to join an existing organization, you should not create a new one. You
                                may have ended up here because:
                            </p>
                            <ul className="m-0 pl-4 list-disc">
                                <li>You're logging in with the wrong email address</li>
                                <li>Your PostHog account is at a different URL</li>
                                <li>You need an invitation from a colleague</li>
                            </ul>
                        </AuthBanner>
                    )}
                </div>
            </AuthSceneCard>
        </AuthScene>
    )
}
