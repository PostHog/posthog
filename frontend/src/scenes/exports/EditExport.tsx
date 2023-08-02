import { SceneExport } from 'scenes/sceneTypes'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { ExportForm } from './ExportForm'

export const scene: SceneExport = {
    component: EditExport,
}

export function EditExport(): JSX.Element {
    const { currentLocation } = useValues(router)
    const exportId = currentLocation.pathname.split('/').slice(-2).pop(0)

    return <ExportForm exportId={exportId} />
}
