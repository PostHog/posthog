import { useValues } from 'kea'

import { LemonCard } from '@posthog/lemon-ui'

import { StopSignHog } from 'lib/components/hedgehogs'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: OrganizationDeactivated,
    logic: organizationLogic,
}

export function OrganizationDeactivated(): JSX.Element {
    const { isNotActiveReason } = useValues(organizationLogic)

    return (
        <div className="max-w-[600px] mx-auto px-2 py-8">
            <LemonCard>
                <div className="flex flex-col gap-4 items-center text-center">
                    <StopSignHog className="w-52 h-52" />
                    <h3>Your organization has been deactivated. {isNotActiveReason}</h3>
                </div>
            </LemonCard>
        </div>
    )
}
