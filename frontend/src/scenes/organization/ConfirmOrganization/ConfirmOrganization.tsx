import React from 'react'
import './ConfirmOrganization.scss'
import { SceneExport } from 'scenes/sceneTypes'
import { organizationLogic } from 'scenes/organizationLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'
import { LemonDivider } from 'lib/components/LemonDivider'
import { IconHelpOutline } from 'lib/components/icons'
import { useValues } from 'kea'
import { confirmOrganizationLogic } from './confirmOrganizationLogic'
import { Field } from 'lib/forms/Field'
import { VerticalForm } from 'lib/forms/VerticalForm'

export const scene: SceneExport = {
    component: ConfirmOrganization,
    logic: organizationLogic,
}

export function ConfirmOrganization(): JSX.Element {
    const { isConfirmOrganizationSubmitting, email } = useValues(confirmOrganizationLogic)

    return (
        <div className="bridge-page ConfirmOrganization">
            <WelcomeLogo view="org-creation-confirmation" />
            <div className="ConfirmOrganization__container-box">
                <p className="ConfirmOrganization__title">Create a new organization</p>
                <div className="ConfirmOrganization__help-box">
                    <div>
                        <IconHelpOutline
                            width={'1.5rem'}
                            height={'1.5rem'}
                            style={{ color: 'var(--warning)' }}
                         />
                    </div>
                    <div style={{ flex: 1 }} className="ml">
                        <p>
                            <strong>Are you sure you want to create a new organization?</strong> If you’re trying to
                            join an existing organization, you should not create a new one. When in doubt, double check
                            with your colleagues to ensure you’re joining the right PostHog organization and instance.
                        </p>
                    </div>
                </div>

                <VerticalForm logic={confirmOrganizationLogic} formKey="confirmOrganization" enableFormOnSubmit>
                    <Field name="email" label="Email">
                        <LemonInput className="ph-ignore-input" value={email} disabled />
                    </Field>

                    <Field name="user_name" label="Your name">
                        <LemonInput className="ph-ignore-input" placeholder="Jane Doe" />
                    </Field>

                    <Field name="organization_name" label="Organization name">
                        <LemonInput className="ph-ignore-input" placeholder="Hogflix Movies" />
                    </Field>

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
                </VerticalForm>

                <div className="text-center terms-and-conditions-text">
                    By creating an account, you agree to our{' '}
                    <a href={`https://posthog.com/terms`} target="_blank" rel="noopener">
                        Terms of Service
                    </a>{' '}
                    and{' '}
                    <a href={`https://posthog.com/privacy`} target="_blank" rel="noopener">
                        Privacy Policy
                    </a>
                    .
                </div>
                <LemonDivider thick dashed />
                <p>Have questions? Visit support or read our documentation</p>
            </div>
        </div>
    )
}
