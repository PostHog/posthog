import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function ConfigureIdJagModal(): JSX.Element {
    const { configureIdJagModalId, isIdJagConfigSubmitting, idJagConfig } = useValues(verifiedDomainsLogic)
    const { setConfigureIdJagModalId } = useActions(verifiedDomainsLogic)

    const idJagReady = Boolean(idJagConfig.id_jag_issuer_url)

    const handleClose = (): void => {
        setConfigureIdJagModalId(null)
    }

    return (
        <LemonModal onClose={handleClose} isOpen={!!configureIdJagModalId} title="" simple>
            <Form logic={verifiedDomainsLogic} formKey="idJagConfig" enableFormOnSubmit className="LemonModal__layout ">
                <LemonModal.Header>
                    <h3>Configure XAA (ID-JAG)</h3>
                </LemonModal.Header>
                <LemonModal.Content className="deprecated-space-y-2">
                    <LemonField
                        name="id_jag_issuer_url"
                        label="IdP issuer URL"
                        info="The trusted identity provider issuer URL. Must match the iss claim on ID-JAG tokens for users on this domain."
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
                        info="Override JWKS discovery. Leave empty to use OIDC discovery at the issuer URL."
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
                        info="Restrict which client_id values are accepted. Leave empty to allow any client_id."
                    >
                        {({ value, onChange }) => (
                            <LemonInputSelect
                                value={value ?? []}
                                onChange={onChange}
                                placeholder="Add client IDs..."
                                mode="multiple"
                                allowCustomValues
                                options={[]}
                            />
                        )}
                    </LemonField>
                    {!idJagReady && (
                        <LemonBanner type="info">
                            XAA will not be enabled until you enter an IdP issuer URL. You can save partial settings as
                            a draft.
                        </LemonBanner>
                    )}
                    <LemonBanner type="info">
                        Configure your IdP to grant <code>user:read</code> plus the scopes each integration needs (for
                        project-scoped APIs, also <code>organization:read</code> and <code>project:read</code>). Tokens
                        issued without the required scopes are rejected with an insufficient-scope error.
                    </LemonBanner>
                </LemonModal.Content>
                <LemonModal.Footer>
                    <LemonButton loading={isIdJagConfigSubmitting} type="primary" htmlType="submit">
                        Save settings
                    </LemonButton>
                </LemonModal.Footer>
            </Form>
        </LemonModal>
    )
}
