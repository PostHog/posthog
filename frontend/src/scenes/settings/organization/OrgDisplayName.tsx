import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconUpload, IconX } from '@posthog/icons'
import { LemonButton, LemonFileInput, LemonInput, lemonToast } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { organizationLogic } from 'scenes/organizationLogic'

export function OrganizationDisplayName(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const [name, setName] = useState(currentOrganization?.name || '')
    const [logoMediaId, setLogoMediaId] = useState(currentOrganization?.logo_media_id || null)

    // Keep these in sync in case it changes outside of this component
    useEffect(() => {
        setName(currentOrganization?.name || '')
        setLogoMediaId(currentOrganization?.logo_media_id || null)
    }, [currentOrganization?.name, currentOrganization?.logo_media_id])

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (_, __, id) => {
            setLogoMediaId(id)
        },
        onError: (detail) => {
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    const nameChanged = name !== (currentOrganization?.name || '')
    const logoChanged = logoMediaId !== (currentOrganization?.logo_media_id || null)
    const hasChanges = nameChanged || logoChanged

    return (
        <div className="flex gap-6 items-start">
            <LemonFileInput
                accept="image/*"
                multiple={false}
                onChange={setFilesToUpload}
                loading={uploading}
                value={filesToUpload}
                disabledReason={restrictionReason}
                callToAction={
                    <div className="relative">
                        <UploadedLogo
                            name={currentOrganization?.name || '?'}
                            entityId={currentOrganization?.id || 1}
                            mediaId={logoMediaId}
                            size="xlarge"
                        />
                        {logoMediaId && (
                            <div className="absolute -inset-2 group">
                                <LemonButton
                                    icon={<IconX />}
                                    onClick={(e) => {
                                        setLogoMediaId(null)
                                        e.preventDefault()
                                    }}
                                    size="small"
                                    tooltip="Reset back to lettermark"
                                    tooltipPlacement="right"
                                    noPadding
                                    className="group-hover:flex hidden absolute right-0 top-0"
                                />
                            </div>
                        )}
                        <div className="flex items-center gap-1 mt-1 justify-center text-muted text-xs">
                            <IconUpload className="text-sm" />
                            Upload
                        </div>
                    </div>
                }
            />
            <div className="flex-1 max-w-120 space-y-3">
                <LemonInput
                    value={name}
                    onChange={setName}
                    disabled={!!restrictionReason}
                    data-attr="organization-name-input-settings"
                    placeholder="Organization name"
                />
                <LemonButton
                    type="primary"
                    onClick={(e) => {
                        e.preventDefault()
                        const updates: Record<string, unknown> = {}
                        if (nameChanged) {
                            updates.name = name
                        }
                        if (logoChanged) {
                            updates.logo_media_id = logoMediaId
                        }
                        updateOrganization(updates)
                    }}
                    disabledReason={
                        restrictionReason
                            ? restrictionReason
                            : !hasChanges
                              ? 'No changes to save'
                              : !name
                                ? 'You must provide a name'
                                : !currentOrganization
                                  ? 'Organization not loaded'
                                  : undefined
                    }
                    loading={currentOrganizationLoading || uploading}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
