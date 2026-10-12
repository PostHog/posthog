import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconTrash, IconUpload } from '@posthog/icons'
import { LemonButton, LemonFileInput, LemonInput, lemonToast } from '@posthog/lemon-ui'

import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { backendAssetUrl } from 'lib/utils/apiHost'

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
    const { brandLogoMediaId, brandLinkUrl } = sharingSettings

    const [linkDraft, setLinkDraft] = useState(brandLinkUrl ?? '')
    useEffect(() => {
        setLinkDraft(brandLinkUrl ?? '')
    }, [brandLinkUrl])

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (_, __, mediaId) => setSharingSettingsValue('brandLogoMediaId', mediaId),
        onError: (detail) => lemonToast.error(`Couldn't upload the logo: ${detail}`),
    })

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
                    Show your logo in the header of the shared dashboard instead of the PostHog logo.
                </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
                {brandLogoMediaId && (
                    <img
                        className="max-h-10 max-w-40 rounded border object-contain p-1"
                        src={backendAssetUrl(`/uploaded_media/${brandLogoMediaId}`)}
                        alt="Your logo"
                    />
                )}
                <LemonFileInput
                    accept="image/*"
                    multiple={false}
                    onChange={setFilesToUpload}
                    value={filesToUpload}
                    loading={uploading}
                    showUploadedFiles={false}
                    callToAction={
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconUpload />}
                            loading={uploading}
                            data-attr="sharing-brand-logo-upload"
                        >
                            {brandLogoMediaId ? 'Replace logo' : 'Upload logo'}
                        </LemonButton>
                    }
                />
                {brandLogoMediaId && (
                    <LemonButton
                        type="secondary"
                        status="danger"
                        size="small"
                        icon={<IconTrash />}
                        onClick={() => setSharingSettingsValue('brandLogoMediaId', null)}
                        disabledReason={
                            uploading
                                ? 'Wait for the new logo to finish uploading'
                                : sharingConfigurationLoading
                                  ? 'Saving…'
                                  : undefined
                        }
                        data-attr="sharing-brand-logo-remove"
                    >
                        Remove logo
                    </LemonButton>
                )}
            </div>
            {brandLogoMediaId && (
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
