import { useActions, useValues } from 'kea'
import { MouseEvent, useEffect, useState } from 'react'

import { IconUpload, IconX } from '@posthog/icons'
import { LemonButton, LemonFileInput, LemonInput, lemonToast } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { organizationLogic } from 'scenes/organizationLogic'

import { QuillOrganizationDisplayName } from './QuillOrganizationDisplayName'

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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const nameChanged = name !== (currentOrganization?.name || '')
    const logoChanged = logoMediaId !== (currentOrganization?.logo_media_id || null)
    const hasChanges = nameChanged || logoChanged

    const saveDisabledReason = restrictionReason
        ? restrictionReason
        : !hasChanges
          ? 'No changes to save'
          : !name
            ? 'You must provide a name'
            : !currentOrganization
              ? 'Organization not loaded'
              : undefined
    const saving = currentOrganizationLoading || uploading

    const resetLogo = (e: MouseEvent): void => {
        setLogoMediaId(null)
        e.preventDefault()
    }

    const save = (e: MouseEvent): void => {
        e.preventDefault()
        const updates: Record<string, unknown> = {}
        if (nameChanged) {
            updates.name = name
        }
        if (logoChanged) {
            updates.logo_media_id = logoMediaId
        }
        updateOrganization(updates)
    }

    if (todayRailNav) {
        return (
            <QuillOrganizationDisplayName
                organization={currentOrganization}
                name={name}
                onNameChange={setName}
                logoMediaId={logoMediaId}
                onResetLogo={resetLogo}
                filesToUpload={filesToUpload}
                onFilesToUploadChange={setFilesToUpload}
                uploading={uploading}
                restrictionReason={restrictionReason}
                saveDisabledReason={saveDisabledReason}
                saving={saving}
                onSave={save}
            />
        )
    }

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
                                    onClick={resetLogo}
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
                <div className="flex items-center gap-2">
                    <LemonButton type="primary" onClick={save} disabledReason={saveDisabledReason} loading={saving}>
                        Save
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
