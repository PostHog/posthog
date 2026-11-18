import { useActions, useValues } from 'kea'
import { ChangeEvent, KeyboardEvent, useState } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Textarea,
} from '@posthog/quill'

import { buildDebugReplayPrompt } from 'scenes/session-recordings/player/player-meta/debugReplayPrompt'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

export function QuillDebugReplayPromptModal({ onClose }: { onClose: () => void }): JSX.Element {
    const { sessionRecordingId, currentPlayerTimeSeconds, debugRecordingPreparing } =
        useValues(sessionRecordingPlayerLogic)
    const { debugRecordingWithAI } = useActions(sessionRecordingPlayerLogic)

    // The default prompt names the current player time, so it is built once when the dialog opens.
    const [defaultPrompt] = useState(() => buildDebugReplayPrompt(sessionRecordingId, currentPlayerTimeSeconds))
    const [prompt, setPrompt] = useState(defaultPrompt)
    const trimmedPrompt = prompt.trim()

    const submit = (): void => {
        if (!trimmedPrompt) {
            return
        }
        debugRecordingWithAI(trimmedPrompt, trimmedPrompt !== defaultPrompt)
        onClose()
    }

    return (
        <Dialog open onOpenChange={(open: boolean) => !open && onClose()}>
            <DialogContent className="max-w-[40rem]">
                <DialogHeader>
                    <DialogTitle>Debug this replay with PostHog AI</DialogTitle>
                    <DialogDescription>
                        Edit the prompt if you want to. PostHog AI gets the recording data along with it.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <Textarea
                        value={prompt}
                        rows={10}
                        autoFocus
                        onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setPrompt(event.target.value)}
                        onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                                event.preventDefault()
                                submit()
                            }
                        }}
                        data-attr="replay-debug-prompt-input"
                    />
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose} data-attr="replay-debug-prompt-cancel">
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={submit}
                        loading={debugRecordingPreparing}
                        disabledReason={trimmedPrompt ? undefined : 'Write a prompt first'}
                        data-attr="replay-debug-prompt-submit"
                    >
                        Send to PostHog AI
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
