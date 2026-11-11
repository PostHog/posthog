import { useActions, useValues } from 'kea'

import { Text } from '@posthog/quill'

import { CanvasComposer } from '../../scene/CanvasComposer'
import { canvasSceneLogic } from '../../scene/canvasSceneLogic'
import { canvasChatLogic } from './canvasChatLogic'

/** Sends a follow-up to the viewer's run, or starts one when they have none. */
export function CanvasChatComposer(): JSX.Element {
    const { draft, chatState, sendError, sending } = useValues(canvasChatLogic)
    const { setDraft, sendMessage } = useActions(canvasChatLogic)
    const { generationStarting } = useValues(canvasSceneLogic)
    const live = chatState === 'running' || chatState === 'awaiting' || chatState === 'starting'

    return (
        <div className="flex flex-col gap-2 border-t border-border p-3">
            {sendError && (
                <Text size="xs" variant="destructive" role="alert">
                    Couldn't send your message. {sendError}
                </Text>
            )}
            <CanvasComposer
                instruction={draft}
                onInstructionChange={(value) => setDraft(value)}
                onSubmit={sendMessage}
                submitting={generationStarting || sending}
                disabledReason={draft.trim() ? null : 'Write a message first'}
                placeholder={live ? 'Send the agent a message' : 'Ask for a change'}
                ariaLabel="Message the agent"
                submitLabel="Send"
                rows={3}
                showSuggestions={false}
                autoFocus={false}
                dataAttr="canvas-chat"
            />
        </div>
    )
}
