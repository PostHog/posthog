import { SceneExport } from 'scenes/sceneTypes'
import { pipelineLogic } from './pipelineLogic'
import { PageHeader } from 'lib/components/PageHeader'

export function Pipeline(): JSX.Element {
    return (
        <div className="pipeline-scene">
            <PageHeader title="Pipeline" />
        </div>
    )
}

export const scene: SceneExport = {
    component: Pipeline,
    logic: pipelineLogic,
}

// TODO: error from import ./pipeline/PipelineScene
// TODO: update https://storybook.posthog.net/?path=/docs/how-to-build-a-scene--docs <- about kea stuff to exclude and have run pnpm ... for type creation
