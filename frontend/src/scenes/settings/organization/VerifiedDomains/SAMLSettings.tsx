import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconShieldLock } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { IdentityProviderDomainPicker } from './IdentityProviderDomainPicker'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function SAMLSettings(): JSX.Element {
    const { isSAMLAvailable, isSamlConfigSubmitting, samlConfig, verifiedDomainsList } = useValues(verifiedDomainsLogic)
    const { preflight } = useValues(preflightLogic)
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })
    const siteUrl = preflight?.site_url ?? window.location.origin
    const samlReady = !!(samlConfig.saml_acs_url && samlConfig.saml_entity_id && samlConfig.saml_x509_cert)
    const selectedDomains = verifiedDomainsList.filter(({ id }) => samlConfig.domain_ids.includes(id))

    return (
        <section className="space-y-3">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h2 className="flex items-center gap-2">
                        <IconShieldLock /> SAML
                    </h2>
                    <p className="text-muted">
                        Configure sign-in through your identity provider and assign it to verified domains.{' '}
                        <Link to="https://posthog.com/docs/data/sso#setting-up-saml" target="_blank" targetBlankIcon>
                            Read the docs
                        </Link>
                    </p>
                </div>
                <LemonTag type={samlReady ? 'success' : 'muted'}>
                    {samlReady ? 'Ready' : samlConfig.id ? 'Needs attention' : 'Not configured'}
                </LemonTag>
            </div>
            <LemonCard className="p-5">
                {!isSAMLAvailable ? (
                    <Link to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}>
                        Upgrade your plan to configure SAML.
                    </Link>
                ) : (
                    <Form logic={verifiedDomainsLogic} formKey="samlConfig" enableFormOnSubmit className="space-y-4">
                        <div className="grid gap-4 lg:grid-cols-2">
                            <LemonField name="name" label="Configuration name">
                                <LemonInput placeholder="Okta production" />
                            </LemonField>
                            <IdentityProviderDomainPicker />
                        </div>
                        <div className="rounded border p-4 space-y-3">
                            <h3>PostHog service provider details</h3>
                            <div className="grid gap-4 lg:grid-cols-2">
                                <LemonField label="ACS consumer URL" name="_ACSConsumerUrl">
                                    <CopyToClipboardInline>{`${siteUrl}/complete/saml/`}</CopyToClipboardInline>
                                </LemonField>
                                <LemonField label="Audience / Entity ID" name="_Audience">
                                    <CopyToClipboardInline>{siteUrl}</CopyToClipboardInline>
                                </LemonField>
                            </div>
                            {selectedDomains.map((domain) => (
                                <LemonField
                                    key={domain.id}
                                    label={`RelayState for ${domain.domain}`}
                                    name={`_${domain.id}`}
                                >
                                    <CopyToClipboardInline>{domain.id}</CopyToClipboardInline>
                                </LemonField>
                            ))}
                        </div>
                        <div className="grid gap-4 lg:grid-cols-2">
                            <LemonField name="saml_acs_url" label="Identity provider sign-on URL">
                                <LemonInput className="ph-ignore-input" placeholder="https://idp.example.com/sso" />
                            </LemonField>
                            <LemonField name="saml_entity_id" label="Identity provider entity ID">
                                <LemonInput className="ph-ignore-input" placeholder="Identity provider entity ID" />
                            </LemonField>
                        </div>
                        <LemonField name="saml_x509_cert" label="X.509 certificate">
                            <LemonTextArea
                                className="ph-ignore-input"
                                minRows={8}
                                placeholder={`-----BEGIN CERTIFICATE-----\nMIICVjCCAb+gAwIBAgIBADANBgkqhkiG9w0BAQ0FADBIMQswCQYDVQQGEwJ1czEL\n-----END CERTIFICATE-----`}
                            />
                        </LemonField>
                        {!samlReady && (
                            <LemonBanner type="info">
                                You can save this as a draft. SAML becomes available after all identity provider fields
                                are filled in.
                            </LemonBanner>
                        )}
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isSamlConfigSubmitting}
                            disabledReason={restrictionReason}
                        >
                            Save SAML settings
                        </LemonButton>
                    </Form>
                )}
            </LemonCard>
        </section>
    )
}
