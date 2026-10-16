import { useActions, useValues } from 'kea'

import { IconUpload, IconX } from '@posthog/icons'
import { LemonButton, LemonFileInput, lemonToast } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { projectLogic } from 'scenes/projectLogic'

export function ProjectLogoUpload(): JSX.Element {
    const { currentProject, currentProjectLoading } = useValues(projectLogic)
    const { updateCurrentProject } = useActions(projectLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (_, __, uploadedMediaId) => updateCurrentProject({ logo_media_id: uploadedMediaId }),
        onError: (detail) => lemonToast.error(`Couldn't upload the logo: ${detail}`),
    })

    const logoMediaId = currentProject?.logo_media_id ?? null

    return (
        <div className="flex items-center gap-4">
            <LemonFileInput
                accept="image/*"
                multiple={false}
                onChange={setFilesToUpload}
                loading={uploading || currentProjectLoading}
                value={filesToUpload}
                disabledReason={restrictionReason}
                callToAction={
                    <div className="flex flex-col items-center gap-1">
                        <UploadedLogo
                            name={currentProject?.name || '?'}
                            entityId={currentProject?.id || 1}
                            mediaId={logoMediaId}
                            size="xlarge"
                            outlinedLettermark
                        />
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            icon={<IconUpload />}
                            disabledReason={restrictionReason}
                            data-attr="project-logo-upload"
                        >
                            Upload
                        </LemonButton>
                    </div>
                }
            />
            {logoMediaId && (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconX />}
                    onClick={() => updateCurrentProject({ logo_media_id: null })}
                    disabledReason={restrictionReason}
                    loading={currentProjectLoading}
                    data-attr="project-logo-remove"
                >
                    Remove logo
                </LemonButton>
            )}
        </div>
    )
}
