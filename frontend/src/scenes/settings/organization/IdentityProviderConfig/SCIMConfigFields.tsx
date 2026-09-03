import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonLabel, LemonSwitch, Link } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonField } from 'lib/lemon-ui/LemonField'

export function SCIMConfigFields({
    scimEnabled,
    scimBaseUrl,
    revealedToken,
    canRegenerateToken,
    tokenLoading,
    disabled,
    onRegenerateToken,
}: {
    scimEnabled: boolean
    scimBaseUrl: string | null
    revealedToken: string | null
    canRegenerateToken: boolean
    tokenLoading: boolean
    disabled: boolean
    onRegenerateToken: () => void
}): JSX.Element {
    const confirmRegenerateToken = (): void => {
        LemonDialog.open({
            title: 'Regenerate SCIM token?',
            description:
                'This invalidates the current token. Update your identity provider with the new token after it is generated.',
            primaryButton: {
                status: 'danger',
                children: 'Regenerate token',
                onClick: onRegenerateToken,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="space-y-4">
            <p>
                Configure SCIM for your organization.{' '}
                <Link to="https://posthog.com/docs/data/sso#setting-up-scim" target="_blank" targetBlankIcon>
                    Read the SCIM setup guide
                </Link>
            </p>
            <LemonField name="scim_enabled">
                {({ value, onChange }) => (
                    <LemonSwitch
                        checked={value}
                        onChange={onChange}
                        label="Enable SCIM provisioning"
                        disabled={disabled}
                    />
                )}
            </LemonField>
            {scimEnabled && (
                <div className="space-y-4">
                    <div>
                        <LemonLabel className="mb-1 block">SCIM base URL</LemonLabel>
                        {scimBaseUrl ? (
                            <CopyToClipboardInline description="SCIM base URL">{scimBaseUrl}</CopyToClipboardInline>
                        ) : (
                            <p className="text-secondary mb-0">
                                Save this configuration to generate the SCIM base URL.
                            </p>
                        )}
                    </div>
                    <div>
                        <LemonLabel className="mb-1 block">Bearer token</LemonLabel>
                        {revealedToken ? (
                            <>
                                <CopyToClipboardInline description="Bearer token" isValueSensitive>
                                    {revealedToken}
                                </CopyToClipboardInline>
                                <LemonBanner type="warning" className="mt-2">
                                    Copy this token now. It will not be shown again.
                                </LemonBanner>
                            </>
                        ) : canRegenerateToken ? (
                            <>
                                <p className="text-secondary">The bearer token is only shown when it is generated.</p>
                                <LemonButton
                                    type="secondary"
                                    icon={<IconRefresh />}
                                    onClick={confirmRegenerateToken}
                                    loading={tokenLoading}
                                    data-attr="regenerate-scim-token"
                                >
                                    Regenerate token
                                </LemonButton>
                            </>
                        ) : (
                            <p className="text-secondary mb-0">Save this configuration to generate a bearer token.</p>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}
