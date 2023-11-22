import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { integrationsLogic } from 'scenes/settings/project/integrationsLogic'

export const scene: SceneExport = {
    component: IntegrationsRedirect,
    logic: integrationsLogic,
}

export function IntegrationsRedirect(): JSX.Element {
    return (
        <div className="text-center gap-4 flex">
            <Spinner />
        </div>
    )
}

export default IntegrationsRedirect
