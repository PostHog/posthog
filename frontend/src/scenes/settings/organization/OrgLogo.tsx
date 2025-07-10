import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonFileInput, lemonToast } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { IconUploadFile } from 'lib/lemon-ui/icons'
import { organizationLogic } from 'scenes/organizationLogic'

export function OrganizationLogo(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const [logoMediaId, setLogoMediaId] = useState(currentOrganization?.logo_media_id || null)

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (_, __, id) => {
            setLogoMediaId(id)
        },
        onError: (detail) => {
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    return (
        <div className="deprecated-space-y-4">
            <LemonFileInput
                accept="image/*"
                multiple={false}
                onChange={setFilesToUpload}
                loading={uploading}
                value={filesToUpload}
                disabled={!!restrictionReason}
                callToAction={
                    <>
                        <div className="relative">
                            <UploadedLogo
                                name={currentOrganization?.name || '?'}
                                entityId={currentOrganization?.id || 1}
                                mediaId={logoMediaId}
                                size="xlarge"
                            />
                            {logoMediaId && (
                                <div className="group absolute -inset-2">
                                    <LemonButton
                                        icon={<IconX />}
                                        onClick={(e) => {
                                            setLogoMediaId(null)
                                            e.preventDefault() // Don't fire LemonFileInput's handler
                                        }}
                                        size="small"
                                        tooltip="Reset back to lettermark"
                                        tooltipPlacement="right"
                                        noPadding
                                        className="absolute right-0 top-0 hidden group-hover:flex"
                                    />
                                </div>
                            )}
                        </div>
                        <IconUploadFile className="ml-1 text-2xl" />
                        <div>
                            Click or drag and drop to upload logo image
                            <br />
                            (192x192 px or larger)
                        </div>
                    </>
                }
            />
            <LemonButton
                type="primary"
                onClick={(e) => {
                    e.preventDefault()
                    updateOrganization({ logo_media_id: logoMediaId })
                }}
                disabledReason={
                    restrictionReason
                        ? restrictionReason
                        : !currentOrganization
                          ? 'Organization not loaded'
                          : logoMediaId === currentOrganization.logo_media_id
                            ? 'Logo unchanged'
                            : undefined
                }
                loading={currentOrganizationLoading || uploading}
            >
                Save logo
            </LemonButton>
        </div>
    )
}
