import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { organizationLogic } from 'scenes/organizationLogic'
import { LemonButton } from 'lib/components/LemonButton'
import api from 'lib/api'

export const scene: SceneExport = {
    component: ConfirmOrganization,
    logic: organizationLogic,
}

export function ConfirmOrganization(): JSX.Element {
    return (
        <div>
            Confirm org
            <LemonButton
                onClick={async () => {
                    const response = await api.create('api/social_signup', {
                        organization_name: 'test',
                        email_opt_in: true,
                    })
                    window.location.href = response.continue_url
                }}
            >
                Complete
            </LemonButton>
        </div>
    )
}
