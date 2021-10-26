import React from 'react'
import { CreateOrganizationModal } from '../CreateOrganizationModal'
import { SceneExport } from 'scenes/sceneTypes'
import { organizationLogic } from 'scenes/organizationLogic'

export const scene: SceneExport = {
    component: Create,
    logic: organizationLogic,
}

export function Create(): JSX.Element {
    return <CreateOrganizationModal isVisible />
}
