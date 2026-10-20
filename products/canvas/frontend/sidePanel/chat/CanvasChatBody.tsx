import { useValues } from 'kea'

import { IconMessage, IconWarning } from '@posthog/icons'
import {
    ChatMarker,
    ChatMarkerContent,
    ChatMarkerIcon,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
    Spinner,
    Text,
} from '@posthog/quill'

import { ReadonlyRunSurface } from 'products/posthog_ai/frontend/api/readableRun'

import { canvasSceneLogic } from '../../scene/canvasSceneLogic'
import { canvasChatLogic } from './canvasChatLogic'

/** Server errors don't always end in a full stop, and the copy after them needs one. */
function asSentence(message: string): string {
    const trimmed = message.trim()
    return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`
}

/** The viewer's run: its conversation once the agent is at work, else what is happening instead. */
export function CanvasChatBody(): JSX.Element {
    const { chatState, chatTask, chatRun, draft } = useValues(canvasChatLogic)
    const { generationError } = useValues(canvasSceneLogic)

    if (chatState === 'loading') {
        return (
            <div className="flex flex-col gap-2 p-3">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-16 w-full" />
                <Skeleton className="h-4 w-1/2" />
            </div>
        )
    }
    if (chatState === 'start-failed') {
        return (
            <Empty className="h-full border-0" data-attr="canvas-chat-start-failed">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconWarning />
                    </EmptyMedia>
                    <EmptyTitle>The agent didn't start</EmptyTitle>
                    <EmptyDescription>
                        {`${asSentence(generationError ?? 'Something stopped the run from starting')}${
                            draft.trim() ? ' Your message is still in the box below, so you can send it again.' : ''
                        }`}
                    </EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }
    if (chatTask && chatRun && chatState !== 'starting') {
        const terminal = chatState === 'finished' || chatState === 'failed'
        return (
            <ReadonlyRunSurface
                // A new run gets a fresh stream.
                key={chatRun.id}
                taskId={chatTask.id}
                runId={chatRun.id}
                interaction={terminal ? 'read-only' : 'live'}
                threadRowClassName="px-3"
                threadListClassName="py-3"
            />
        )
    }
    if (chatState === 'starting') {
        return (
            <div className="flex flex-col gap-1 p-3" data-attr="canvas-chat-starting">
                <ChatMarker status="running">
                    <ChatMarkerIcon>
                        <Spinner />
                    </ChatMarkerIcon>
                    <ChatMarkerContent>Starting the agent</ChatMarkerContent>
                </ChatMarker>
                <Text size="xs" variant="muted">
                    Its messages show here once it starts working. This can take a minute.
                </Text>
            </div>
        )
    }
    return (
        <Empty className="h-full border-0">
            <EmptyHeader>
                <EmptyMedia variant="icon">
                    <IconMessage />
                </EmptyMedia>
                <EmptyTitle>No agent run yet</EmptyTitle>
                <EmptyDescription>
                    Describe a change below and an agent edits the canvas. Your conversation with it shows here.
                </EmptyDescription>
            </EmptyHeader>
        </Empty>
    )
}
