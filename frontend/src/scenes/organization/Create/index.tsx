import React, { useState } from 'react'
import { CreateOrganizationModal } from '../CreateOrganizationModal'
import { SceneExport } from 'scenes/sceneTypes'
import { organizationLogic } from 'scenes/organizationLogic'

export const scene: SceneExport = {
    component: OrganizationCreate,
    logic: organizationLogic,
}

export function OrganizationCreate(): JSX.Element {
    const [isVisible, setIsVisible] = useState(true)

    return <CreateOrganizationModal  isVisible={isVisible} onClose={() => setIsVisible(false)} />
}
