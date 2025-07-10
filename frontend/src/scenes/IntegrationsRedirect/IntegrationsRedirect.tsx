import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: IntegrationsRedirect,
    logic: integrationsLogic,
}

export function IntegrationsRedirect(): JSX.Element {
    return (
        <div className="flex gap-4 text-center">
            <Spinner />
        </div>
    )
}

export default IntegrationsRedirect
