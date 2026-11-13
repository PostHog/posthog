import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconSparkles } from '@posthog/icons'

import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { debugReplayChatLogic } from 'scenes/session-recordings/player/player-meta/debugReplayChatLogic'
import { buildDebugReplayContextItems } from 'scenes/session-recordings/player/player-meta/debugReplayPrompt'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { QuillDebugReplayPromptModal } from './QuillDebugReplayPromptModal'

const PREPARING = 'Loading the recording data for PostHog AI'

export function useDebugReplayMenuItems(enabled: boolean): { items: LemonMenuItems; modal: JSX.Element | null } {
    const { sessionRecordingId, debugRecordingPreparing } = useValues(sessionRecordingPlayerLogic)
    const { taskIdBySessionRecordingId, openingSessionRecordingId } = useValues(debugReplayChatLogic)
    const { openDebugChat } = useActions(debugReplayChatLogic)
    const [promptModalOpen, setPromptModalOpen] = useState(false)

    const contextItems = useMemo(() => buildDebugReplayContextItems(sessionRecordingId), [sessionRecordingId])
    useAttachedContext(contextItems, { active: enabled })

    if (!enabled) {
        return { items: [], modal: null }
    }

    const preparingReason = debugRecordingPreparing ? PREPARING : undefined
    const openPrompt = (): void => setPromptModalOpen(true)
    const items = taskIdBySessionRecordingId[sessionRecordingId]
        ? [
              {
                  label: 'Open debug chat',
                  icon: <IconSparkles />,
                  onClick: () => openDebugChat(sessionRecordingId),
                  tooltip: 'Opens the PostHog AI chat that debugged this recording.',
                  disabledReason:
                      preparingReason ??
                      (openingSessionRecordingId === sessionRecordingId ? 'Opening the chat' : undefined),
                  'data-attr': 'replay-debug-chat-open',
              },
              {
                  label: 'Debug again in a new chat',
                  icon: <IconSparkles />,
                  onClick: openPrompt,
                  disabledReason: preparingReason,
                  'data-attr': 'replay-debug-with-ai-again',
              },
          ]
        : [
              {
                  label: 'Debug this replay',
                  icon: <IconSparkles />,
                  onClick: openPrompt,
                  tooltip: 'Asks PostHog AI what went wrong in this recording. You can edit the prompt first.',
                  disabledReason: preparingReason,
                  'data-attr': 'replay-debug-with-ai',
              },
          ]

    return {
        items: [{ key: 'debug-replay', items }],
        modal: promptModalOpen ? <QuillDebugReplayPromptModal onClose={() => setPromptModalOpen(false)} /> : null,
    }
}
