import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { CreateProjectModal } from '../CreateProjectModal'

export const scene: SceneExport = {
    component: ProjectCreate,
    logic: teamLogic,
}

export function ProjectCreate(): JSX.Element {
    const { projectCreationForbiddenReason } = useValues(organizationLogic)

    return projectCreationForbiddenReason ? (
        <LemonBanner type="warning" className="mt-5">
            {projectCreationForbiddenReason}
        </LemonBanner>
    ) : (
        // Give the inline scene a working exit (Cancel + close) so a failed create doesn't trap the user.
        <CreateProjectModal isVisible inline onClose={() => router.actions.push(urls.projectHomepage())} />
    )
}
