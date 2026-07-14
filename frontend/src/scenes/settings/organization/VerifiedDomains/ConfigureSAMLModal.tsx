import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { Link } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { IdentityProviderDomainPicker } from './IdentityProviderDomainPicker'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function ConfigureSAMLModal(): JSX.Element {
    const { configureSAMLModalId, isSamlConfigSubmitting, samlConfig, verifiedDomainsList } =
        useValues(verifiedDomainsLogic)
    const { setConfigureSAMLModalId } = useActions(verifiedDomainsLogic)
    const { preflight } = useValues(preflightLogic)
    const siteUrl = preflight?.site_url ?? window.location.origin
    const samlReady = samlConfig.saml_acs_url && samlConfig.saml_entity_id && samlConfig.saml_x509_cert
    const selectedDomains = verifiedDomainsList.filter(({ id }) => samlConfig.domain_ids.includes(id))

    return (
        <LemonModal onClose={() => setConfigureSAMLModalId(null)} isOpen={!!configureSAMLModalId} title="" simple>
            <Form logic={verifiedDomainsLogic} formKey="samlConfig" enableFormOnSubmit className="LemonModal__layout">
                <LemonModal.Header>
                    <h3>{samlConfig.id ? 'Edit SAML configuration' : 'Add SAML configuration'}</h3>
                </LemonModal.Header>
                <LemonModal.Content className="deprecated-space-y-2">
                    <p>
                        Configure one SAML connection and reuse it across every domain served by the same identity
                        provider.{' '}
                        <Link to="https://posthog.com/docs/data/sso#setting-up-saml" target="_blank" targetBlankIcon>
                            Read the docs
                        </Link>
                    </p>
                    <LemonField name="name" label="Configuration name">
                        <LemonInput placeholder="Okta production" />
                    </LemonField>
                    <IdentityProviderDomainPicker />
                    <div className="rounded border p-3 space-y-2">
                        <h4>PostHog service provider details</h4>
                        <LemonField label="ACS consumer URL" name="_ACSConsumerUrl">
                            <CopyToClipboardInline>{`${siteUrl}/complete/saml/`}</CopyToClipboardInline>
                        </LemonField>
                        <LemonField label="Audience / Entity ID" name="_Audience">
                            <CopyToClipboardInline>{siteUrl}</CopyToClipboardInline>
                        </LemonField>
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
                    <LemonField name="saml_acs_url" label="Identity provider sign-on URL">
                        <LemonInput className="ph-ignore-input" placeholder="https://idp.example.com/sso" />
                    </LemonField>
                    <LemonField name="saml_entity_id" label="Identity provider entity ID">
                        <LemonInput className="ph-ignore-input" placeholder="Identity provider entity ID" />
                    </LemonField>
                    <LemonField name="saml_x509_cert" label="X.509 certificate">
                        <LemonTextArea
                            className="ph-ignore-input"
                            minRows={10}
                            placeholder={`-----BEGIN CERTIFICATE-----\nMIICVjCCAb+gAwIBAgIBADANBgkqhkiG9w0BAQ0FADBIMQswCQYDVQQGEwJ1czEL\n-----END CERTIFICATE-----`}
                        />
                    </LemonField>
                    {!samlReady && (
                        <LemonBanner type="info">
                            You can save this as a draft. SAML becomes available after all identity provider fields are
                            filled in.
                        </LemonBanner>
                    )}
                </LemonModal.Content>
                <LemonModal.Footer>
                    <LemonButton type="secondary" onClick={() => setConfigureSAMLModalId(null)}>
                        Cancel
                    </LemonButton>
                    <LemonButton loading={isSamlConfigSubmitting} type="primary" htmlType="submit">
                        Save configuration
                    </LemonButton>
                </LemonModal.Footer>
            </Form>
        </LemonModal>
    )
}
