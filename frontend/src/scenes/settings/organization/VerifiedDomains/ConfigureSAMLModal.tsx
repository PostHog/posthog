import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'
import { Field } from 'lib/forms/Field'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Form } from 'kea-forms'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Link } from '@posthog/lemon-ui'

export function ConfigureSAMLModal(): JSX.Element {
    const { configureSAMLModalId, isSamlConfigSubmitting, samlConfig } = useValues(verifiedDomainsLogic)
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
                <LemonModal.Content className="space-y-2">
                    <p>
                        <Link to={'https://posthog.com/docs/data/sso#setting-up-saml'} target="_blank" targetBlankIcon>
                            Read the docs
                        </Link>
                    </p>
                    <Field label="ACS Consumer URL" name="_ACSConsumerUrl">
                        <CopyToClipboardInline>{`${siteUrl}/complete/saml/`}</CopyToClipboardInline>
                    </Field>
                    <Field label="RelayState" name="_RelayState">
                        <CopyToClipboardInline>{configureSAMLModalId || 'unknown'}</CopyToClipboardInline>
                    </Field>
                    <Field label="Audience / Entity ID" name="_Audience">
                        <CopyToClipboardInline>{siteUrl}</CopyToClipboardInline>
                    </Field>
                    <Field name="saml_acs_url" label="SAML ACS URL">
                        <LemonInput className="ph-ignore-input" placeholder="Your IdP's ACS or single sign-on URL." />
                    </Field>
                    <Field name="saml_entity_id" label="SAML Entity ID">
                        <LemonInput className="ph-ignore-input" placeholder="Entity ID provided by your IdP." />
                    </Field>
                    <Field name="saml_x509_cert" label="SAML X.509 Certificate">
                        <LemonTextArea
                            className="ph-ignore-input"
                            minRows={10}
                            placeholder={`Enter the public certificate of your IdP. Keep all line breaks.\n-----BEGIN CERTIFICATE-----\nMIICVjCCAb+gAwIBAgIBADANBgkqhkiG9w0BAQ0FADBIMQswCQYDVQQGEwJ1czEL\n-----END CERTIFICATE-----`}
                        />
                    </Field>
                    {!samlReady && (
                        <LemonBanner type="info">
                            SAML will not be enabled unless you enter all attributes above. However you can still
                            settings as draft.
                        </LemonBanner>
                    )}
                </LemonModal.Content>
                <LemonModal.Footer>
                    <LemonButton loading={isSamlConfigSubmitting} type="primary" htmlType="submit">
                        Save settings
                    </LemonButton>
                </LemonModal.Footer>
            </Form>
        </LemonModal>
    )
}
