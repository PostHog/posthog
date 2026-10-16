import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonInput, LemonSwitch, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { backendAssetUrl } from 'lib/utils/apiHost'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

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
    const { sharingSettings, sharingConfigurationLoading } = useValues(sharingLogic(logicProps))
    const { setSharingSettingsValue } = useActions(sharingLogic(logicProps))
    const { currentOrganization } = useValues(organizationLogic)
    const { showOrganizationLogo, brandLinkUrl } = sharingSettings
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
            <div>
                <div className="text-sm font-semibold">Your branding</div>
                <p className="mb-0 text-xs text-secondary">
                    Show your organization logo in the header of the shared dashboard.{' '}
                    {logoMediaId ? (
                        <>
                            To change it, update the logo in <Link to={logoSettingsUrl}>organization settings</Link>.
                        </>
                    ) : (
                        <>
                            Your organization has no logo yet. Upload one in{' '}
                            <Link to={logoSettingsUrl}>organization settings</Link>.
                        </>
                    )}
                </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
                {logoMediaId && (
                    <img
                        className="max-h-10 max-w-40 rounded border object-contain p-1"
                        src={backendAssetUrl(`/uploaded_media/${logoMediaId}`)}
                        alt="Your organization logo"
                    />
                )}
                <LemonSwitch
                    bordered
                    label="Show organization logo"
                    checked={!!logoMediaId && showOrganizationLogo}
                    onChange={(checked) => setSharingSettingsValue('showOrganizationLogo', checked)}
                    disabledReason={
                        !logoMediaId
                            ? 'Upload a logo in organization settings first'
                            : sharingConfigurationLoading
                              ? 'Saving…'
                              : undefined
                    }
                    data-attr="sharing-show-organization-logo"
                />
            </div>
            {logoMediaId && showOrganizationLogo && (
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
