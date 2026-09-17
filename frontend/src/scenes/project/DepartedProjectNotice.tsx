import { useActions, useValues } from 'kea'

import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { formatDate } from 'lib/utils/datetime'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { departedProjectsLogic } from './departedProjectsLogic'

/** Tells an organization that lost a project where the project went, so nobody reads the move as a deletion. */
export function DepartedProjectNotice(): JSX.Element | null {
    const { mostRecentDeparture, currentOrganization } = useValues(departedProjectsLogic)
    const { updateCurrentOrganization } = useActions(userLogic)

    if (!mostRecentDeparture) {
        return null
    }

    const {
        project_id,
        project_name,
        target_organization_id,
        target_organization_name,
        target_organization_accessible,
        moved_at,
    } = mostRecentDeparture

    return (
        <LemonBanner
            type="info"
            className="w-full text-left"
            action={
                target_organization_accessible
                    ? {
                          children: `Open ${project_name}`,
                          onClick: () => updateCurrentOrganization(target_organization_id, urls.project(project_id)),
                      }
                    : undefined
            }
        >
            <p className="font-semibold mb-1">
                {project_name} moved to {target_organization_name}
            </p>
            <p className="mb-0">
                It left {currentOrganization?.name ?? 'this organization'} on {formatDate(dayjs(moved_at))}. The project
                and its data are still there.
                {!target_organization_accessible &&
                    ` You are not a member of ${target_organization_name}, so ask an admin there for access.`}
            </p>
        </LemonBanner>
    )
}
