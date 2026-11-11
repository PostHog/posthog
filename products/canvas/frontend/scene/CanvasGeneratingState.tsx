import { useValues } from 'kea'

import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle, Spinner } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { canvasSceneLogic } from './canvasSceneLogic'

/** Shown while the agent writes a canvas that has nothing to render yet. */
export function CanvasGeneratingState(): JSX.Element {
    const { canvas, generationPhase } = useValues(canvasSceneLogic)
    const taskId = canvas?.generation_task_id
    const starting = generationPhase !== 'running'

    return (
        <Empty className="h-full border-0">
            <EmptyHeader>
                <Spinner />
                <EmptyTitle className="quill-shimmer">
                    {starting ? 'Starting the agent' : 'Building your canvas'}
                </EmptyTitle>
                <EmptyDescription>
                    {starting
                        ? 'The agent is getting ready. This can take a minute.'
                        : 'The agent is writing the canvas. It shows here as soon as the first version is ready.'}
                </EmptyDescription>
            </EmptyHeader>
            {taskId && (
                <EmptyContent>
                    <Button
                        variant="outline"
                        render={<LinkPrimitive to={urls.taskDetail(taskId)} />}
                        data-attr="canvas-generating-view-task"
                    >
                        View the agent's task
                    </Button>
                </EmptyContent>
            )}
        </Empty>
    )
}
