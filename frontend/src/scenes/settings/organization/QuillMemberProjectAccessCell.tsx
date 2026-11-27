import { useActions, useValues } from 'kea'

import { Badge, Button, Skeleton, Text } from '@posthog/quill'

import { projectDataFreshnessLogic } from 'lib/components/Account/projectDataFreshnessLogic'

import { OrganizationMemberType } from '~/types'

import { accessibleProjects, orderByActivity } from './memberProjectAccess'
import { memberProjectAccessLogic } from './memberProjectAccessLogic'

const PROJECT_BADGES_SHOWN = 3

export function QuillMemberProjectAccessCell({ member }: { member: OrganizationMemberType }): JSX.Element {
    const { projectAccess, projectAccessLoading } = useValues(memberProjectAccessLogic)
    const { openProjectAccessModal } = useActions(memberProjectAccessLogic)
    const { freshnessByTeamId } = useValues(projectDataFreshnessLogic)

    if (projectAccessLoading) {
        return <Skeleton className="h-5 w-32" />
    }

    // A failed load must not read as "this member has no projects"
    if (!projectAccess) {
        return (
            <Text size="xs" variant="muted" render={<span />} className="m-0">
                –
            </Text>
        )
    }

    const projects = orderByActivity(accessibleProjects(projectAccess[member.id] ?? []), freshnessByTeamId)
    if (projects.length === 0) {
        return (
            <Text size="xs" variant="muted" render={<span />} className="m-0">
                No projects
            </Text>
        )
    }

    const visibleProjects = projects.slice(0, PROJECT_BADGES_SHOWN)
    const hiddenCount = projects.length - visibleProjects.length

    return (
        <div className="flex flex-wrap gap-1 items-center">
            {visibleProjects.map((project) => (
                <Badge
                    key={project.team_id}
                    className="max-w-40 truncate cursor-pointer"
                    render={<button type="button" onClick={() => openProjectAccessModal(member)} />}
                >
                    {project.team_name}
                </Badge>
            ))}
            {hiddenCount > 0 && (
                <Button
                    variant="link"
                    size="inline"
                    onClick={() => openProjectAccessModal(member)}
                    data-attr="org-member-project-access-more"
                >
                    {`+${hiddenCount} more`}
                </Button>
            )}
        </div>
    )
}
