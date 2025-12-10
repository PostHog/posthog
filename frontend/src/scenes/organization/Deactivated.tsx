import { useValues } from 'kea'

import { LemonCard } from '@posthog/lemon-ui'

import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: OrganizationDeactivated,
    logic: organizationLogic,
}

export function OrganizationDeactivated(): JSX.Element {
    const { isNotActiveReason } = useValues(organizationLogic)

    return (
        <div className="container mx-auto px-2 py-8">
            <LemonCard>
                <h3>Your organization has been deactivated. {isNotActiveReason}</h3>
            </LemonCard>
        </div>
    )
}
