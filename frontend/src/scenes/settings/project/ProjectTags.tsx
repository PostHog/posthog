import { useActions, useValues } from 'kea'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { useRestrictedArea, RestrictionScope } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { projectLogic } from 'scenes/projectLogic'

import { tagsModel } from '~/models/tagsModel'

export function ProjectTags(): JSX.Element {
    const { currentProject, currentProjectLoading } = useValues(projectLogic)
    const { updateCurrentProject } = useActions(projectLogic)
    const { tags: tagsAvailable } = useValues(tagsModel)

    // Projects carry no resource-level access controls, so tag writes are gated by project
    // membership, which is exactly what the API's own permission check requires.
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })

    if (!currentProject) {
        return <LemonSkeleton className="w-40 h-5" />
    }

    if (restrictionReason) {
        return <ObjectTags tags={currentProject.tags ?? []} staticOnly data-attr="project-tags" />
    }

    return (
        <ObjectTags
            tags={currentProject.tags ?? []}
            tagsAvailable={tagsAvailable}
            onChange={(tags) => updateCurrentProject({ tags })}
            saving={currentProjectLoading}
            data-attr="project-tags"
        />
    )
}
