import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

export const scene: SceneExport = {
    component: IntegrationsRedirect,
    logic: integrationsLogic,
}

export function IntegrationsRedirect(): JSX.Element {
    const { oauthCallbackTimedOut } = useValues(integrationsLogic)

    if (oauthCallbackTimedOut) {
        return (
            <div className="flex flex-col items-center justify-center gap-3 min-h-full p-4 text-center">
                <h2 className="m-0">This is taking longer than expected</h2>
                <p className="text-secondary m-0 max-w-md">
                    Your integration hasn't finished connecting. Open integration settings to check on it or try again.
                </p>
                <LemonButton type="primary" to={urls.settings('project-integrations')}>
                    Go to integration settings
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex items-center justify-center gap-4 min-h-full text-center">
            <Spinner />
        </div>
    )
}

export default IntegrationsRedirect
