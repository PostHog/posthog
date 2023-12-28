import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { sourceModalLogic } from 'scenes/data-warehouse/external/sourceModalLogic'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: DataWarehouseRedirectScene,
    logic: sourceModalLogic,
}

export function DataWarehouseRedirectScene(): JSX.Element {
    return (
        <div className="text-center gap-4 flex">
            <Spinner />
        </div>
    )
}

export default DataWarehouseRedirectScene
