import { useValues } from 'kea'

import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle, Spinner } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { canvasSceneLogic } from './canvasSceneLogic'

/** Shown while the agent writes a canvas that has nothing to render yet. */
export function CanvasGeneratingState(): JSX.Element {
    const { canvas } = useValues(canvasSceneLogic)
    const taskId = canvas?.generation_task_id

    return (
        <Empty className="h-full">
            <EmptyHeader>
                <Spinner />
                <EmptyTitle className="quill-shimmer">Building your canvas</EmptyTitle>
                <EmptyDescription>
                    The agent is writing the canvas. It shows here as soon as the first version is ready.
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
