import React from 'react'
import { CreateOrganizationModal } from '../CreateOrganizationModal'
import { SceneExport } from 'scenes/sceneTypes'
import { organizationLogic } from 'scenes/organizationLogic'

export const scene: SceneExport = {
    component: OrganizationCreate,
    logic: organizationLogic,
}

export function OrganizationCreate(): JSX.Element {
    return <CreateOrganizationModal isVisible mask={false} />
}
