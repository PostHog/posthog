import { SceneExport } from 'scenes/sceneTypes'
import { pipelineLogic } from './pipelineLogic'

export function Pipeline(): JSX.Element {
    return (
        // TODO: consolidate on a recommended naming convention
        <div className="pipeline-scene">WIP: Pipeline Scene!</div>
    )
}

export const scene: SceneExport = {
    component: Pipeline,
    logic: pipelineLogic,
}

// TODO: error from import ./pipeline/PipelineScene
// TODO: update https://storybook.posthog.net/?path=/docs/how-to-build-a-scene--docs <- about kea stuff to exclude and have run pnpm ... for type creation
