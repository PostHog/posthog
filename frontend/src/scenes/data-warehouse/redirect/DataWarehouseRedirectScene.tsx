import { Spinner } from '@posthog/lemon-ui'
import { SceneExport } from 'scenes/sceneTypes'

import { sourceWizardLogic } from '../new/sourceWizardLogic'

export const scene: SceneExport = {
    component: DataWarehouseRedirectScene,
    logic: sourceWizardLogic,
}

export function DataWarehouseRedirectScene(): JSX.Element {
    return (
        <div className="text-center gap-4 flex">
            <Spinner />
        </div>
    )
}

export default DataWarehouseRedirectScene
