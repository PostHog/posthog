import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { CreateProjectModal } from '../CreateProjectModal'
import { DepartedProjectNotice } from '../DepartedProjectNotice'

export const scene: SceneExport = {
    component: ProjectCreate,
    logic: teamLogic,
}

export function ProjectCreate(): JSX.Element {
    const { projectCreationForbiddenReason, currentOrganization } = useValues(organizationLogic)

    return (
        <div className="flex flex-col gap-4 mt-5">
            {/* An organization with no projects often just lost one to a move, which reads as a deletion */}
            {currentOrganization?.projects.length === 0 && <DepartedProjectNotice />}
            {projectCreationForbiddenReason ? (
                <LemonBanner type="warning">{projectCreationForbiddenReason}</LemonBanner>
            ) : (
                // Give the inline scene a working exit (Cancel + close) so a failed create doesn't trap the user.
                <CreateProjectModal isVisible inline onClose={() => router.actions.push(urls.projectHomepage())} />
            )}
        </div>
    )
}
