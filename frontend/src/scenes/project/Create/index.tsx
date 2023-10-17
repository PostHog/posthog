import { CreateProjectModal } from '../CreateProjectModal'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { useValues } from 'kea'
import { organizationLogic } from 'scenes/organizationLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

export const scene: SceneExport = {
    component: ProjectCreate,
    logic: teamLogic,
}

export function ProjectCreate(): JSX.Element {
    const { projectCreationForbiddenReason } = useValues(organizationLogic)

    return projectCreationForbiddenReason ? (
        <LemonBanner type="warning" className="mt-5">
            {`Switch to a project that you have access to. If you need a new project or access to an existing one that's private, ask a team member with administrator permissions. Reason: ${projectCreationForbiddenReason}`}
        </LemonBanner>
    ) : (
        <CreateProjectModal isVisible inline />
    )
}
