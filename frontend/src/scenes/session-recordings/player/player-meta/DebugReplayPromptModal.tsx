import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { buildDebugReplayPrompt } from './debugReplayPrompt'

export function DebugReplayPromptModal({ onClose }: { onClose: () => void }): JSX.Element {
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
        <LemonModal
            isOpen
            onClose={onClose}
            title="Debug this replay with PostHog AI"
            description="Edit the prompt if you want to. PostHog AI gets the recording data along with it."
            width={640}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose} data-attr="replay-debug-prompt-cancel">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submit}
                        loading={debugRecordingPreparing}
                        disabledReason={trimmedPrompt ? undefined : 'Write a prompt first'}
                        data-attr="replay-debug-prompt-submit"
                    >
                        Send to PostHog AI
                    </LemonButton>
                </>
            }
        >
            <LemonTextArea
                value={prompt}
                onChange={setPrompt}
                onPressCmdEnter={submit}
                minRows={8}
                maxRows={16}
                autoFocus
                data-attr="replay-debug-prompt-input"
            />
        </LemonModal>
    )
}
