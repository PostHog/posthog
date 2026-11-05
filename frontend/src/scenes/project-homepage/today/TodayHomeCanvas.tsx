import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
} from '@posthog/quill'

import { CanvasScene } from 'products/canvas/frontend/scene/CanvasScene'

import { todayHomeCanvasLogic } from './todayHomeCanvasLogic'

/** The Canvas tab: the person's own freeform canvas, with the same toolbar and editing as the canvas page. */
export function TodayHomeCanvas(): JSX.Element {
    const { homeCanvasId, homeCanvasIdLoading, homeCanvasFailed, spacesUnavailable } = useValues(todayHomeCanvasLogic)
    const { retryHomeCanvas } = useActions(todayHomeCanvasLogic)

    if (homeCanvasId) {
        return <CanvasScene id={homeCanvasId} />
    }
    if ((homeCanvasFailed || spacesUnavailable) && !homeCanvasIdLoading) {
        return (
            <Empty className="h-full border-0">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconWarning />
                    </EmptyMedia>
                    <EmptyTitle>Your canvas didn't load</EmptyTitle>
                    <EmptyDescription>Check your connection and try again.</EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button variant="outline" onClick={retryHomeCanvas} data-attr="today-home-canvas-retry">
                        Try again
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }
    return (
        <div className="flex h-full flex-col gap-3 p-4" aria-busy aria-label="Loading your canvas">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-full w-full" />
        </div>
    )
}
