import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconRefresh } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'

import { IdentityProviderDomainPicker } from './IdentityProviderDomainPicker'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function ConfigureSCIMModal(): JSX.Element {
    const { configureSCIMModalId, isScimConfigSubmitting, scimConfig, scimPlaintextToken, verifiedDomainsList } =
        useValues(verifiedDomainsLogic)
    const { regenerateScimToken, setConfigureSCIMModalId } = useActions(verifiedDomainsLogic)
    const selectedDomains = verifiedDomainsList.filter(({ id }) => scimConfig.domain_ids.includes(id))

    return (
        <LemonModal onClose={() => setConfigureSCIMModalId(null)} isOpen={!!configureSCIMModalId} title="" simple>
            <Form logic={verifiedDomainsLogic} formKey="scimConfig" enableFormOnSubmit className="LemonModal__layout">
                <LemonModal.Header>
                    <h3>{scimConfig.id ? 'Edit SCIM configuration' : 'Add SCIM configuration'}</h3>
                </LemonModal.Header>
                <LemonModal.Content className="deprecated-space-y-2">
                    <p>
                        Use one bearer token for every domain provisioned by this SCIM connection.{' '}
                        <Link to="https://posthog.com/docs/data/sso/scim" target="_blank" targetBlankIcon>
                            Read the docs
                        </Link>
                    </p>
                    <LemonField name="name" label="Configuration name">
                        <LemonInput placeholder="Okta provisioning" />
                    </LemonField>
                    <IdentityProviderDomainPicker />
                    <LemonField name="scim_enabled" label="Provisioning status">
                        {({ value, onChange }) => (
                            <LemonSwitch
                                checked={value || false}
                                onChange={onChange}
                                label={value ? 'SCIM provisioning enabled' : 'SCIM provisioning disabled'}
                            />
                        )}
                    </LemonField>
                    {selectedDomains.length > 0 && (
                        <div className="rounded border p-3 space-y-2">
                            <h4>SCIM base URLs</h4>
                            {selectedDomains.map((domain) => (
                                <div key={domain.id} className="flex flex-col gap-1">
                                    <span className="font-semibold">{domain.domain}</span>
                                    {domain.scim_base_url ? (
                                        <CopyToClipboardInline>{domain.scim_base_url}</CopyToClipboardInline>
                                    ) : (
                                        <span className="text-muted">
                                            Save and enable this configuration to generate the URL.
                                        </span>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                    {scimPlaintextToken && (
                        <LemonBanner type="success">
                            <div className="space-y-2">
                                <p>Copy this bearer token now. It will not be shown again.</p>
                                <CopyToClipboardInline>{scimPlaintextToken}</CopyToClipboardInline>
                            </div>
                        </LemonBanner>
                    )}
                    {scimConfig.id && scimConfig.scim_enabled && (
                        <LemonButton
                            type="secondary"
                            icon={<IconRefresh />}
                            onClick={() =>
                                LemonDialog.open({
                                    title: 'Regenerate SCIM bearer token?',
                                    description: 'The current token will stop working immediately.',
                                    primaryButton: {
                                        children: 'Regenerate token',
                                        onClick: () => regenerateScimToken(scimConfig.id as string),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }
                        >
                            Regenerate token
                        </LemonButton>
                    )}
                </LemonModal.Content>
                <LemonModal.Footer>
                    <LemonButton type="secondary" onClick={() => setConfigureSCIMModalId(null)}>
                        Close
                    </LemonButton>
                    <LemonButton loading={isScimConfigSubmitting} type="primary" htmlType="submit">
                        Save configuration
                    </LemonButton>
                </LemonModal.Footer>
            </Form>
        </LemonModal>
    )
}
