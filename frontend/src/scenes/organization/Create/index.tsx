import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { CreateOrganizationModal } from '../CreateOrganizationModal'

export const scene: SceneExport = {
    component: OrganizationCreate,
    logic: organizationLogic,
}

export function OrganizationCreate(): JSX.Element {
    return <CreateOrganizationModal isVisible inline />
}
