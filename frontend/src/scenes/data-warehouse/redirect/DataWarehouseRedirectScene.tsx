import { Spinner } from '@posthog/lemon-ui'
import { SceneExport } from 'scenes/sceneTypes'

import { sourceWizardLogic } from '../new/sourceWizardLogic'

export const scene: SceneExport = {
    component: DataWarehouseRedirectScene,
    logic: sourceWizardLogic,
}

export function DataWarehouseRedirectScene(): JSX.Element {
    return (
        <div className="text-left flex flex-col">
            <Spinner />
        </div>
    )
}

export default DataWarehouseRedirectScene
