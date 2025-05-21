import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: SessionSummaries,
}

export function SessionSummaries(): JSX.Element {
    return (
        <div className="flex flex-col gap-4 p-4">
            <h1>Session Summaries</h1>
            <p>Coming soon...</p>
        </div>
    )
}
