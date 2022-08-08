import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import React from 'react'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'
import { Field } from 'lib/forms/Field'
import { AlertMessage } from 'lib/components/AlertMessage'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { LemonTextArea } from 'lib/components/LemonTextArea/LemonTextArea'
import { LemonModal } from 'lib/components/LemonModal'
import { VerticalForm } from 'lib/forms/VerticalForm'

export function ConfigureSAMLModal(): JSX.Element {
    const { configureSAMLModalId, isSamlConfigSubmitting, samlConfig } = useValues(verifiedDomainsLogic)
    const { setConfigureSAMLModalId } = useActions(verifiedDomainsLogic)

    const samlReady = samlConfig.saml_acs_url && samlConfig.saml_entity_id && samlConfig.saml_x509_cert

    const handleClose = (): void => {
        setConfigureSAMLModalId(null)
        // clean()
    }

    return (
        <LemonModal onClose={handleClose} isOpen={!!configureSAMLModalId} title="" simple>
            <VerticalForm
                logic={verifiedDomainsLogic}
                formKey="samlConfig"
                enableFormOnSubmit
                className="LemonModal__layout"
            >
                <LemonModal.Header>
                    <h3>Configure SAML authentication and provisioning</h3>
                </LemonModal.Header>
                <LemonModal.Content>
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
                        <AlertMessage type="info" style={{ marginBottom: 16 }}>
                            SAML will not be enabled unless you enter all attributes above. However you can still
                            settings as draft.
                        </AlertMessage>
                    )}
                </LemonModal.Content>
                <LemonModal.Footer>
                    <LemonButton loading={isSamlConfigSubmitting} type="primary" htmlType="submit">
                        Save settings
                    </LemonButton>
                </LemonModal.Footer>
            </VerticalForm>
        </LemonModal>
    )
}
