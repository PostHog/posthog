import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import {
    isProjectGroupTag,
    projectGroupFromTags,
    projectGroupTagFromName,
    PROJECT_GROUP_TAG_PREFIX,
    uniqueProjectGroupNames,
} from 'lib/components/Account/projectGroupTags'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { useRestrictedArea, RestrictionScope } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel, OrganizationMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { identifierToHuman } from 'lib/utils/strings'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'

import { tagsModel } from '~/models/tagsModel'

export function ProjectTags(): JSX.Element {
    const { currentProject, currentProjectLoading } = useValues(projectLogic)
    const { updateCurrentProject } = useActions(projectLogic)
    const { tags: tagsAvailable } = useValues(tagsModel)
    const { currentOrganization } = useValues(organizationLogic)
    const [groupInput, setGroupInput] = useState('')

    // Regular project tags use project access; the API also restricts group changes to organization admins.
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })

    const currentTags = currentProject?.tags ?? []
    const group = projectGroupFromTags(currentTags)
    const groupTag = group ? `${PROJECT_GROUP_TAG_PREFIX}${group}` : null
    const regularTags = currentTags.filter((tag) => !isProjectGroupTag(tag))
    const canEditProjectGroup =
        !restrictionReason && (currentOrganization?.membership_level ?? 0) >= OrganizationMembershipLevel.Admin
    const nextGroupTag = projectGroupTagFromName(groupInput)
    const groupChanged = nextGroupTag !== groupTag
    const projectGroupOptions = useMemo(
        () =>
            uniqueProjectGroupNames(currentOrganization?.teams?.map((team) => team.project_group) ?? []).map(
                (value) => ({ key: value, value, label: identifierToHuman(value, 'sentence') })
            ),
        [currentOrganization?.teams]
    )

    useEffect(() => {
        setGroupInput(group ?? '')
    }, [group])

    if (!currentProject) {
        return <LemonSkeleton className="w-40 h-5" />
    }

    if (restrictionReason) {
        return <ObjectTags tags={regularTags} staticOnly data-attr="project-tags" />
    }

    return (
        <div className="flex flex-col gap-3">
            <ObjectTags
                tags={regularTags}
                tagsAvailable={tagsAvailable.filter((tag) => !isProjectGroupTag(tag))}
                onChange={(tags) => updateCurrentProject({ tags: groupTag ? [...tags, groupTag] : tags })}
                saving={currentProjectLoading}
                data-attr="project-tags"
            />
            {canEditProjectGroup && (
                <form
                    className="flex flex-col gap-1 max-w-80"
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (currentProjectLoading || !groupChanged) {
                            return
                        }
                        updateCurrentProject({ tags: nextGroupTag ? [...regularTags, nextGroupTag] : regularTags })
                    }}
                >
                    <LemonLabel>Project group</LemonLabel>
                    <div className="flex gap-1">
                        <LemonInputSelect
                            className="flex-1"
                            mode="single"
                            allowCustomValues
                            disabled={currentProjectLoading}
                            value={groupInput ? [groupInput] : []}
                            onChange={(values) => setGroupInput(values[0] ?? '')}
                            options={projectGroupOptions}
                            inputTransform={(input) => input.slice(0, 200)}
                            placeholder="For example, production apps"
                            data-attr="project-group-input"
                        />
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            disabled={!groupChanged}
                            loading={currentProjectLoading}
                            data-attr="project-group-save"
                        >
                            Save
                        </LemonButton>
                    </div>
                </form>
            )}
        </div>
    )
}
