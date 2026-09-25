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
        target_project_accessible,
        moved_at,
    } = mostRecentDeparture

    // The destination is named only to someone who can reach it, so fall back to a description
    const destination = target_organization_name ?? 'another organization'
    const openAction =
        target_project_accessible && target_organization_id
            ? {
                  children: `Open ${project_name}`,
                  onClick: () => updateCurrentOrganization(target_organization_id, urls.project(project_id)),
              }
            : undefined

    return (
        <LemonBanner type="info" className="w-full text-left" action={openAction}>
            <p className="font-semibold mb-1">
                {project_name} moved to {destination}
            </p>
            <p className="mb-0">
                It left {currentOrganization?.name ?? 'this organization'} on {formatDate(dayjs(moved_at))}. The project
                and its data are still there.
                {!openAction &&
                    (target_organization_name
                        ? ` Ask an admin of ${target_organization_name} for access.`
                        : ' Ask an admin of the organization it moved to for access.')}
            </p>
        </LemonBanner>
    )
}
