import { LemonBanner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

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
        <CreateProjectModal isVisible inline />
    )
}
