import { CreateProjectModal } from '../CreateProjectModal'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { useValues } from 'kea'
import { organizationLogic } from 'scenes/organizationLogic'
import { AlertMessage } from 'lib/components/AlertMessage'

export const scene: SceneExport = {
    component: ProjectCreate,
    logic: teamLogic,
}

export function ProjectCreate(): JSX.Element {
    const { projectCreationForbiddenReason } = useValues(organizationLogic)

    return projectCreationForbiddenReason ? (
        <AlertMessage type="warning" className="mt-5">
            {projectCreationForbiddenReason}
        </AlertMessage>
    ) : (
        <CreateProjectModal isVisible inline />
    )
}
