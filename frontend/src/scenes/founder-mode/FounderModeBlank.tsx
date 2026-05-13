import { SceneExport } from 'scenes/sceneTypes'

export function FounderModeBlank(): JSX.Element {
    return (
        <main className="min-h-screen flex items-center justify-center bg-bg-primary">
            <p className="text-2xl">Hello world</p>
        </main>
    )
}

export const scene: SceneExport = {
    component: FounderModeBlank,
}
