import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { combineUrl } from 'kea-router'

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
import { urls } from 'scenes/urls'

import { confirmOrganizationLogic } from './confirmOrganizationLogic'

export const scene: SceneExport = {
    component: ConfirmOrganization,
    logic: organizationLogic,
}

export function ConfirmOrganization(): JSX.Element {
    const { isConfirmOrganizationSubmitting, email, next } = useValues(confirmOrganizationLogic)

    const loginUrl = combineUrl(urls.login(), next ? { next } : {}).url

    return (
        <BridgePage view="org-creation-confirmation" hedgehog>
            <h2>Create a new organization</h2>
            <OtherRegionHint />
            <div className="flex-1">
                <LemonBanner type="info" className="mb-4">
                    <p className="font-semibold mb-1">Trying to join an existing organization?</p>
                    <p className="mb-1">
                        If your team already uses PostHog, don't create a new organization here — you won't be able to
                        see their projects or data. To get access instead:
                    </p>
                    <ul className="list-disc pl-4 mb-2">
                        <li>
                            Ask an admin of that organization to <strong>invite you</strong> by email
                        </li>
                        <li>
                            If you have another PostHog account,{' '}
                            <Link to={loginUrl}>log in with a different email address</Link>
                        </li>
                        <li>Your team's PostHog account may be hosted at a different URL</li>
                    </ul>
                </LemonBanner>
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
