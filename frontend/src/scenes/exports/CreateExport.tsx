import { SceneExport } from 'scenes/sceneTypes'
import { ExportForm } from './ExportForm'

export const scene: SceneExport = {
    component: CreateExport,
}

export function CreateExport(): JSX.Element {
    return <ExportForm exportId={null} />
}
