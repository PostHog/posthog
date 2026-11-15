import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconUpload, IconX } from '@posthog/icons'
import { LemonButton, LemonFileInput, LemonInput, lemonToast } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { organizationLogic } from 'scenes/organizationLogic'
import { isProjectNameTaken } from 'scenes/project/isProjectNameTaken'
import { projectLogic } from 'scenes/projectLogic'

const NAME_TAKEN_REASON = 'There is already a project with this name in this organization. Choose a different name.'

export function ProjectNameAndLogo(): JSX.Element {
    const { currentProject, currentProjectLoading } = useValues(projectLogic)
    const { updateCurrentProject } = useActions(projectLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const [name, setName] = useState(currentProject?.name || '')
    const [logoMediaId, setLogoMediaId] = useState(currentProject?.logo_media_id ?? null)

    useEffect(() => {
        setName(currentProject?.name || '')
        setLogoMediaId(currentProject?.logo_media_id ?? null)
    }, [currentProject?.name, currentProject?.logo_media_id])

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (_, __, uploadedMediaId) => setLogoMediaId(uploadedMediaId),
        onError: (detail) => lemonToast.error(`Couldn't upload the logo: ${detail}`),
    })

    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    // A rename patches the project, so the uniqueness rule applies to the project's name. That can
    // differ from the environment's name, which is what `teamLogic` holds.
    const trimmedName = name.trim()
    const nameTaken = isProjectNameTaken(trimmedName, currentOrganization?.projects, {
        excludeProjectId: currentProject?.id,
        currentName: currentProject?.name,
    })
    const nameChanged = trimmedName !== currentProject?.name
    const logoChanged = logoMediaId !== (currentProject?.logo_media_id ?? null)

    const saveDisabledReason =
        restrictionReason ||
        (!currentProject && 'Loading the project') ||
        (!trimmedName && 'Enter a name') ||
        (nameTaken && NAME_TAKEN_REASON) ||
        (uploading && 'Wait for the logo to finish uploading') ||
        (!nameChanged && !logoChanged && 'No changes to save') ||
        null

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
                    <div className="relative flex flex-col items-center gap-1">
                        <UploadedLogo
                            name={currentProject?.name || '?'}
                            entityId={currentProject?.id || 1}
                            mediaId={logoMediaId}
                            size="xlarge"
                            outlinedLettermark
                        />
                        {logoMediaId && !restrictionReason && (
                            <div className="absolute -inset-2 group">
                                <LemonButton
                                    icon={<IconX />}
                                    onClick={(e) => {
                                        e.preventDefault()
                                        e.stopPropagation()
                                        setLogoMediaId(null)
                                    }}
                                    size="small"
                                    tooltip="Remove logo"
                                    tooltipPlacement="right"
                                    noPadding
                                    className="absolute right-0 top-0 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                                    data-attr="project-logo-remove"
                                />
                            </div>
                        )}
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            icon={<IconUpload className="text-secondary" />}
                            disabledReason={restrictionReason}
                            data-attr="project-logo-upload"
                        >
                            <span className="text-secondary font-normal">Upload</span>
                        </LemonButton>
                    </div>
                }
            />
            <div className="flex-1 max-w-120 flex flex-col gap-3">
                <LemonField.Pure error={nameTaken ? NAME_TAKEN_REASON : undefined}>
                    <LemonInput
                        value={name}
                        onChange={setName}
                        disabledReason={restrictionReason}
                        placeholder="Project name"
                        data-attr="project-name-input-settings"
                    />
                </LemonField.Pure>
                <div>
                    <LemonButton
                        type="primary"
                        onClick={() =>
                            updateCurrentProject({
                                ...(nameChanged ? { name: trimmedName } : {}),
                                ...(logoChanged ? { logo_media_id: logoMediaId } : {}),
                            })
                        }
                        disabledReason={saveDisabledReason}
                        loading={currentProjectLoading}
                        data-attr="project-name-and-logo-save"
                    >
                        Save
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
