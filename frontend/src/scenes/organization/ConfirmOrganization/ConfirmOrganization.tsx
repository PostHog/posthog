import React from 'react'
import './ConfirmOrganization.scss'
import { SceneExport } from 'scenes/sceneTypes'
import { organizationLogic } from 'scenes/organizationLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'
import { LemonDivider } from 'lib/components/LemonDivider'
import { useActions, useValues } from 'kea'
import { confirmOrganizationLogic } from './confirmOrganizationLogic'
import { Field } from 'lib/forms/Field'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { urls } from 'scenes/urls'

export const scene: SceneExport = {
    component: ConfirmOrganization,
    logic: organizationLogic,
}

export function ConfirmOrganization(): JSX.Element {
    const { isConfirmOrganizationSubmitting, email, showNewOrgWarning } = useValues(confirmOrganizationLogic)
    const { setShowNewOrgWarning } = useActions(confirmOrganizationLogic)
    console.log(showNewOrgWarning)

    return (
        <div className="bridge-page ConfirmOrganization">
            <WelcomeLogo view="org-creation-confirmation" />
            <div className="ConfirmOrganization__container-box">
                <p className="ConfirmOrganization__title text-center">Create a new organization</p>
                <div className="ConfirmOrganization__help-box">
                    <div style={{ flex: 1 }}>
                        <p>
                            <strong>
                                Trying to join an existing organization?{' '}
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
                            <div>
                                <div style={{ height: '0.5rem' }} />
                                <p>
                                    If you're trying to join an existing organization, you should not create a new one.
                                    Some reasons that you may accidentally end up here are:
                                    <ul style={{ paddingInlineStart: '1rem', marginBottom: 0, marginBlockEnd: 0 }}>
                                        <li>You're logging in with the wrong email address</li>
                                        <li>Your PostHog account is at a different URL</li>
                                        <li>You need an invitation from a colleague</li>
                                    </ul>
                                </p>
                            </div>
                        </AnimatedCollapsible>
                    </div>
                </div>

                <VerticalForm logic={confirmOrganizationLogic} formKey="confirmOrganization" enableFormOnSubmit>
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

                    <LemonButton
                        className="mt-4"
                        fullWidth
                        center
                        size="large"
                        type="secondary"
                        loading={isConfirmOrganizationSubmitting}
                        to={urls.signup()}
                    >
                        Cancel
                    </LemonButton>
                </VerticalForm>

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
                <LemonDivider thick dashed style={{ marginTop: 24, marginBottom: 24 }} />
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
            </div>
        </div>
    )
}
