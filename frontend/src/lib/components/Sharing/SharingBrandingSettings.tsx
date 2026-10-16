import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { backendAssetUrl } from 'lib/utils/apiHost'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { AvailableFeature } from '~/types'

import { upgradeModalLogic } from '../UpgradeModal/upgradeModalLogic'
import { SharingLogicProps, sharingLogic } from './sharingLogic'

function isHttpUrl(value: string): boolean {
    try {
        const url = new URL(value)
        return url.protocol === 'http:' || url.protocol === 'https:'
    } catch {
        return false
    }
}

export interface SharingBrandingSettingsProps {
    logicProps: SharingLogicProps
}

export function SharingBrandingSettings({ logicProps }: SharingBrandingSettingsProps): JSX.Element {
    const { sharingSettings, sharingConfigurationLoading, whitelabelAvailable } = useValues(sharingLogic(logicProps))
    const { setSharingSettingsValue, setBrandingMode } = useActions(sharingLogic(logicProps))
    const { currentOrganization } = useValues(organizationLogic)
    const { showOrganizationLogo, brandLinkUrl, whitelabel } = sharingSettings
    const { showUpgradeModal } = useActions(upgradeModalLogic)
    let brandingMode: 'posthog' | 'organization' | 'none' = 'posthog'
    if (whitelabel && whitelabelAvailable) {
        brandingMode = showOrganizationLogo ? 'organization' : 'none'
    }
    const savingReason = sharingConfigurationLoading ? 'Saving…' : undefined
    const upgradeReason = whitelabelAvailable ? undefined : 'Available on Boost and higher plans'
    const logoMediaId = currentOrganization?.logo_media_id ?? null
    const logoSettingsUrl = urls.settings('organization-details', 'organization-display-name')

    const [linkDraft, setLinkDraft] = useState(brandLinkUrl ?? '')
    useEffect(() => {
        setLinkDraft(brandLinkUrl ?? '')
    }, [brandLinkUrl])

    const trimmedLink = linkDraft.trim()
    const linkError =
        trimmedLink && !isHttpUrl(trimmedLink) ? 'Enter a link that starts with http:// or https://' : undefined
    const saveLink = (): void => {
        const nextLink = trimmedLink || null
        if (!linkError && nextLink !== (brandLinkUrl ?? null)) {
            setSharingSettingsValue('brandLinkUrl', nextLink)
        }
    }

    return (
        <div className="col-span-2 rounded border p-3 deprecated-space-y-3">
            <fieldset>
                <legend className="mb-2 text-sm font-semibold">Branding</legend>
                <LemonRadio
                    aria-label="Branding"
                    value={brandingMode}
                    onChange={setBrandingMode}
                    options={[
                        {
                            value: 'posthog',
                            label: 'PostHog branding',
                            disabledReason: savingReason,
                            'data-attr': 'sharing-branding-posthog',
                        },
                        {
                            value: 'organization',
                            label: 'Your organization logo',
                            disabledReason:
                                upgradeReason ||
                                savingReason ||
                                (!logoMediaId ? 'Upload a logo in organization settings first' : undefined),
                            'data-attr': 'sharing-show-organization-logo',
                        },
                        {
                            value: 'none',
                            label: 'No branding',
                            disabledReason: upgradeReason || savingReason,
                            'data-attr': 'sharing-branding-none',
                        },
                    ]}
                />
            </fieldset>
            {!whitelabelAvailable && (
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-secondary">
                        Use your own logo or remove PostHog branding on Boost and higher plans.
                    </span>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => showUpgradeModal(AvailableFeature.WHITE_LABELLING)}
                        data-attr="sharing-branding-upgrade"
                    >
                        Upgrade to Boost
                    </LemonButton>
                </div>
            )}
            {whitelabelAvailable && (
                <div className="flex flex-wrap items-center gap-2">
                    {logoMediaId && (
                        <img
                            className="max-h-10 max-w-40 rounded border object-contain p-1"
                            src={backendAssetUrl(`/uploaded_media/${logoMediaId}`)}
                            alt="Your organization logo"
                        />
                    )}
                    <p className="mb-0 text-xs text-secondary">
                        {logoMediaId ? 'Change your logo in ' : 'Upload your logo in '}
                        <Link to={logoSettingsUrl}>organization settings</Link>.
                    </p>
                </div>
            )}
            {logoMediaId && brandingMode === 'organization' && (
                <LemonField.Pure label="Logo link" help="Where viewers go when they click your logo" error={linkError}>
                    <LemonInput
                        value={linkDraft}
                        onChange={setLinkDraft}
                        onBlur={saveLink}
                        onPressEnter={saveLink}
                        placeholder="https://example.com"
                        size="small"
                        data-attr="sharing-brand-link-url"
                    />
                </LemonField.Pure>
            )}
        </div>
    )
}
