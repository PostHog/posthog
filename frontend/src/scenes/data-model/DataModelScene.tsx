import { SceneExport } from "scenes/sceneTypes"
import { dataModelSceneLogic } from "./dataModelSceneLogic"
import { DatabaseTable } from "scenes/data-management/database/DatabaseTable"
import { TableFields } from "./TableFields"
import ScrollableDraggableCanvas from "./DotGridBackground"

export const scene: SceneExport = {
    component: DataModelScene,
    logic: dataModelSceneLogic,
}

export function DataModelScene(): JSX.Element {
    return <div>
        <ScrollableDraggableCanvas />
    </div>
}


