import { useValues } from 'kea'

import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { Button, ChatMarker, ChatMarkerContent, ChatMarkerIcon, Spinner, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { canvasChatLogic } from './canvasChatLogic'

const STATUS_COPY = {
    running: 'The agent is working on the canvas',
    awaiting: 'The agent finished. Send a message to keep going.',
    finished: 'The agent finished this run',
    failed: "The agent's run stopped before it finished",
} as const

/** One line above the chat that says where the viewer's run is, with a link to its task. */
export function CanvasChatStatus(): JSX.Element | null {
    const { chatState, chatTaskId, chatRun } = useValues(canvasChatLogic)

    // A starting run says so in the chat body, so the status line waits until the agent is at work.
    if (chatState !== 'running' && chatState !== 'awaiting' && chatState !== 'finished' && chatState !== 'failed') {
        return null
    }
    const markerStatus =
        chatState === 'finished' || chatState === 'awaiting' ? 'done' : chatState === 'failed' ? 'error' : 'running'
    return (
        <div className="flex flex-col gap-1 border-b border-border px-3 py-2" data-attr="canvas-chat-status">
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                <ChatMarker status={markerStatus} className="min-w-0">
                    <ChatMarkerIcon>
                        {markerStatus === 'running' ? (
                            <Spinner />
                        ) : markerStatus === 'done' ? (
                            <IconCheckCircle />
                        ) : (
                            <IconWarning />
                        )}
                    </ChatMarkerIcon>
                    <ChatMarkerContent>{STATUS_COPY[chatState]}</ChatMarkerContent>
                </ChatMarker>
                {chatTaskId && (
                    <Button
                        size="xs"
                        variant="link-muted"
                        render={<LinkPrimitive to={urls.taskDetail(chatTaskId)} />}
                        data-attr="canvas-chat-open-task"
                    >
                        Open task
                    </Button>
                )}
            </div>
            {chatState === 'failed' && chatRun?.error_message && (
                <Text size="xs" variant="muted" className="line-clamp-3">
                    {chatRun.error_message}
                </Text>
            )}
        </div>
    )
}
