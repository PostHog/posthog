import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { IdentityProviderDomainPicker } from './IdentityProviderDomainPicker'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function ConfigureIdJagModal(): JSX.Element {
    const { configureIdJagModalId, isIdJagConfigSubmitting, idJagConfig } = useValues(verifiedDomainsLogic)
    const { setConfigureIdJagModalId } = useActions(verifiedDomainsLogic)

    return (
        <LemonModal onClose={() => setConfigureIdJagModalId(null)} isOpen={!!configureIdJagModalId} title="" simple>
            <Form logic={verifiedDomainsLogic} formKey="idJagConfig" enableFormOnSubmit className="LemonModal__layout">
                <LemonModal.Header>
                    <h3>{idJagConfig.id ? 'Edit XAA configuration' : 'Add XAA configuration'}</h3>
                </LemonModal.Header>
                <LemonModal.Content className="deprecated-space-y-2">
                    <LemonField name="name" label="Configuration name">
                        <LemonInput placeholder="WorkOS production" />
                    </LemonField>
                    <IdentityProviderDomainPicker />
                    <LemonField
                        name="id_jag_issuer_url"
                        label="Identity provider issuer URL"
                        info="This must match the iss claim on ID-JAG tokens for every assigned domain."
                    >
                        <LemonInput
                            className="ph-ignore-input"
                            placeholder="https://idp.example.com"
                            autoComplete="off"
                        />
                    </LemonField>
                    <LemonField
                        name="id_jag_jwks_url"
                        label="JWKS URL (optional)"
                        info="Leave empty to use OIDC discovery from the issuer URL."
                    >
                        <LemonInput
                            className="ph-ignore-input"
                            placeholder="https://idp.example.com/.well-known/jwks.json"
                            autoComplete="off"
                        />
                    </LemonField>
                    <LemonField
                        name="id_jag_allowed_clients"
                        label="Allowed client IDs (optional)"
                        info="Leave empty to allow any client_id."
                    >
                        {({ value, onChange }) => (
                            <LemonInputSelect
                                value={value || []}
                                onChange={onChange}
                                placeholder="Add client IDs"
                                mode="multiple"
                                allowCustomValues
                                options={[]}
                            />
                        )}
                    </LemonField>
                    {!idJagConfig.id_jag_issuer_url && (
                        <LemonBanner type="info">
                            You can save this as a draft. XAA becomes available after an issuer URL is added.
                        </LemonBanner>
                    )}
                </LemonModal.Content>
                <LemonModal.Footer>
                    <LemonButton type="secondary" onClick={() => setConfigureIdJagModalId(null)}>
                        Cancel
                    </LemonButton>
                    <LemonButton loading={isIdJagConfigSubmitting} type="primary" htmlType="submit">
                        Save configuration
                    </LemonButton>
                </LemonModal.Footer>
            </Form>
        </LemonModal>
    )
}
