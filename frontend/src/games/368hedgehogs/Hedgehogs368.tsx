import { SceneExport } from 'scenes/sceneTypes'

export function Hedgehogs368(): JSX.Element {
    return (
        <div>
            <p>Hedgehogs come here. Here's a demo</p>
            <iframe src="https://368chickens.com/" className="w-full h-[80vh]" />
        </div>
    )
}

export const scene: SceneExport = {
    component: Hedgehogs368,
}
