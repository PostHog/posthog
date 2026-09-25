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
import { Spinner } from 'lib/lemon-ui/Spinner'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function ConfigureSAMLModal(): JSX.Element {
    const { configureSAMLModalId, configureSAMLModalLoading, isSamlConfigSubmitting, samlConfig } =
        useValues(verifiedDomainsLogic)
    const { setConfigureSAMLModalId } = useActions(verifiedDomainsLogic)
    const { preflight } = useValues(preflightLogic)
    const siteUrl = preflight?.site_url ?? window.location.origin

    const samlReady = samlConfig.saml_acs_url && samlConfig.saml_entity_id && samlConfig.saml_x509_cert

    const handleClose = (): void => {
        setConfigureSAMLModalId(null)
        // clean()
    }

    return (
        <LemonModal onClose={handleClose} isOpen={!!configureSAMLModalId} title="" simple>
            <Form logic={verifiedDomainsLogic} formKey="samlConfig" enableFormOnSubmit className="LemonModal__layout ">
                <LemonModal.Header>
                    <h3>Configure SAML authentication and provisioning</h3>
                </LemonModal.Header>
                <LemonModal.Content className="deprecated-space-y-2">
                    {configureSAMLModalLoading ? (
                        <div className="flex min-h-40 items-center justify-center">
                            <Spinner size="large" captureTime />
                        </div>
                    ) : (
                        <>
                            <p>
                                <Link
                                    to="https://posthog.com/docs/data/sso#setting-up-saml"
                                    target="_blank"
                                    targetBlankIcon
                                >
                                    Read the docs
                                </Link>
                            </p>
                            <LemonField
                                label="PostHog ACS consumer URL"
                                name="_ACSConsumerUrl"
                                help="Copy this into your identity provider. Do not enter it in the fields below."
                            >
                                <CopyToClipboardInline>{`${siteUrl}/complete/saml/`}</CopyToClipboardInline>
                            </LemonField>
                            <LemonField label="Relay state" name="_RelayState">
                                <CopyToClipboardInline>
                                    {samlConfig.saml_relay_state || 'unknown'}
                                </CopyToClipboardInline>
                            </LemonField>
                            <LemonField label="Audience / entity ID" name="_Audience">
                                <CopyToClipboardInline>{siteUrl}</CopyToClipboardInline>
                            </LemonField>
                            <LemonField
                                name="saml_acs_url"
                                label="Identity provider sign-on URL"
                                help="The URL PostHog sends people to when they sign in. Okta calls it the sign-on URL, Microsoft Entra ID calls it the login URL."
                            >
                                <LemonInput className="ph-ignore-input" placeholder="https://idp.example.com/sso" />
                            </LemonField>
                            <LemonField name="saml_entity_id" label="SAML entity ID">
                                <LemonInput
                                    className="ph-ignore-input"
                                    placeholder="Entity ID provided by your identity provider"
                                />
                            </LemonField>
                            <LemonField name="saml_x509_cert" label="SAML X.509 certificate">
                                <LemonTextArea
                                    className="ph-ignore-input"
                                    minRows={10}
                                    placeholder={`Enter the public certificate from your identity provider. Keep all line breaks.\n-----BEGIN CERTIFICATE-----\nMIICVjCCAb+gAwIBAgIBADANBgkqhkiG9w0BAQ0FADBIMQswCQYDVQQGEwJ1czEL\n-----END CERTIFICATE-----`}
                                />
                            </LemonField>
                            {!samlReady && (
                                <LemonBanner type="info">
                                    SAML remains disabled until you enter the sign-on URL, entity ID, and X.509
                                    certificate. You can save a partial configuration.
                                </LemonBanner>
                            )}
                        </>
                    )}
                </LemonModal.Content>
                <LemonModal.Footer>
                    <LemonButton
                        loading={isSamlConfigSubmitting}
                        disabled={configureSAMLModalLoading}
                        type="primary"
                        htmlType="submit"
                    >
                        Save settings
                    </LemonButton>
                </LemonModal.Footer>
            </Form>
        </LemonModal>
    )
}
