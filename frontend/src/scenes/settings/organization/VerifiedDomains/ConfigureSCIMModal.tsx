import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconRefresh } from '@posthog/icons'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'

import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function ConfigureSCIMModal(): JSX.Element {
    const { configureSCIMModalId, scimConfig, scimConfigLoading } = useValues(verifiedDomainsLogic)
    const { setConfigureSCIMModalId, enableScim, disableScim, regenerateScimToken } = useActions(verifiedDomainsLogic)
    const [tokenJustRevealed, setTokenJustRevealed] = useState(false)

    const handleClose = (): void => {
        setConfigureSCIMModalId(null)
        setTokenJustRevealed(false)
    }

    const handleToggleScim = async (): Promise<void> => {
        if (!configureSCIMModalId) {
            return
        }

        if (scimConfig.scim_enabled) {
            LemonDialog.open({
                title: 'Disable SCIM?',
                description:
                    'Your identity provider will no longer be able to manage users. SAML authentication will continue to work.',
                primaryButton: {
                    status: 'danger',
                    children: 'Disable SCIM',
                    onClick: async () => {
                        await disableScim(configureSCIMModalId)
                    },
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        } else {
            await enableScim(configureSCIMModalId)
            setTokenJustRevealed(true)
        }
    }

    const handleRegenerateToken = async (): Promise<void> => {
        if (!configureSCIMModalId) {
            return
        }

        LemonDialog.open({
            title: 'Regenerate SCIM token?',
            description:
                'This will invalidate the current token. You will need to update your identity provider with the new token.',
            primaryButton: {
                status: 'danger',
                children: 'Regenerate token',
                onClick: async () => {
                    await regenerateScimToken(configureSCIMModalId)
                    setTokenJustRevealed(true)
                },
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    const showToken = tokenJustRevealed && scimConfig.scim_bearer_token

    return (
        <LemonModal onClose={handleClose} isOpen={!!configureSCIMModalId} title="" simple>
            <div className="LemonModal__layout">
                <LemonModal.Header>
                    <h3>Configure SCIM provisioning</h3>
                </LemonModal.Header>
                <LemonModal.Content className="space-y-2">
                    {/* TODO: Add docs link once SCIM docs are published */}
                    {/* <p>
                        <Link to="https://posthog.com/docs/data/scim" target="_blank" targetBlankIcon>
                            Read the docs
                        </Link>
                    </p> */}

                    <div className="space-y-1">
                        <LemonLabel>Enable SCIM</LemonLabel>
                        <LemonSwitch
                            checked={scimConfig.scim_enabled ?? false}
                            onChange={handleToggleScim}
                            disabled={scimConfigLoading}
                            label={
                                <span className="font-normal">{scimConfig.scim_enabled ? 'Enabled' : 'Disabled'}</span>
                            }
                        />
                    </div>

                    {scimConfig.scim_enabled && (
                        <>
                            <div>
                                <LemonLabel className="block mb-1">SCIM Base URL</LemonLabel>
                                <CopyToClipboardInline description="SCIM base URL">
                                    {scimConfig.scim_base_url || ''}
                                </CopyToClipboardInline>
                            </div>

                            <div>
                                <LemonLabel className="block mb-1">Bearer Token</LemonLabel>
                                {showToken ? (
                                    <>
                                        <CopyToClipboardInline description="Bearer token">
                                            {scimConfig.scim_bearer_token || ''}
                                        </CopyToClipboardInline>
                                        <LemonBanner type="warning" className="my-2">
                                            Save this token, it will only be shown once.
                                        </LemonBanner>
                                    </>
                                ) : (
                                    <>
                                        <p className="text-muted">
                                            The bearer token is only displayed once when generated.
                                        </p>
                                        <LemonButton
                                            type="secondary"
                                            onClick={handleRegenerateToken}
                                            icon={<IconRefresh />}
                                            loading={scimConfigLoading}
                                        >
                                            Regenerate token
                                        </LemonButton>
                                    </>
                                )}
                            </div>
                        </>
                    )}
                </LemonModal.Content>
                <LemonModal.Footer>
                    <LemonButton type="secondary" onClick={handleClose}>
                        Close
                    </LemonButton>
                </LemonModal.Footer>
            </div>
        </LemonModal>
    )
}
