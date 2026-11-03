import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconChevronDown, IconSparkles } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import {
    DebugChatSummary,
    debugReplayChatLogic,
} from 'scenes/session-recordings/player/player-meta/debugReplayChatLogic'
import { buildDebugReplayContextItems } from 'scenes/session-recordings/player/player-meta/debugReplayPrompt'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { isTerminalRunStatus, useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { QuillDebugReplayPromptModal } from './QuillDebugReplayPromptModal'

const PREPARING = 'Loading the recording data for PostHog AI'

function debugChatTooltip(debugChatSummary: DebugChatSummary | undefined): JSX.Element | string {
    if (debugChatSummary?.summary) {
        return (
            <div className="space-y-1">
                <div className="max-h-80 overflow-y-auto whitespace-pre-line">{debugChatSummary.summary}</div>
                <div className="text-xs text-muted-foreground">Click to open the chat.</div>
            </div>
        )
    }
    if (debugChatSummary && !isTerminalRunStatus(debugChatSummary.runStatus)) {
        return 'PostHog AI is still debugging this recording. Click to open the chat.'
    }
    return 'Opens the PostHog AI chat that debugged this recording.'
}

export function QuillDebugReplayButton(): JSX.Element {
    const { sessionRecordingId, debugRecordingPreparing } = useValues(sessionRecordingPlayerLogic)
    const { taskIdBySessionRecordingId, openingSessionRecordingId, debugChatSummaryBySessionRecordingId } =
        useValues(debugReplayChatLogic)
    const { openDebugChat, loadDebugChatSummary } = useActions(debugReplayChatLogic)
    const [promptModalOpen, setPromptModalOpen] = useState(false)

    const contextItems = useMemo(() => buildDebugReplayContextItems(sessionRecordingId), [sessionRecordingId])
    useAttachedContext(contextItems)

    const hasDebugChat = !!taskIdBySessionRecordingId[sessionRecordingId]
    const openingDebugChat = openingSessionRecordingId === sessionRecordingId
    const debugChatSummary = debugChatSummaryBySessionRecordingId[sessionRecordingId]

    useEffect(() => {
        if (hasDebugChat && !debugChatSummary) {
            loadDebugChatSummary(sessionRecordingId)
        }
    }, [hasDebugChat, debugChatSummary, sessionRecordingId, loadDebugChatSummary])

    const promptModal = promptModalOpen ? (
        <QuillDebugReplayPromptModal onClose={() => setPromptModalOpen(false)} />
    ) : null

    if (!hasDebugChat) {
        return (
            <>
                <Button
                    size="xs"
                    onClick={() => setPromptModalOpen(true)}
                    loading={debugRecordingPreparing}
                    tooltip={
                        debugRecordingPreparing
                            ? PREPARING
                            : 'Asks PostHog AI what went wrong in this recording. You can edit the prompt first.'
                    }
                    data-attr="replay-debug-with-ai"
                >
                    <IconSparkles />
                    Debug this replay
                </Button>
                {promptModal}
            </>
        )
    }

    return (
        <>
            <ButtonGroup>
                <Button
                    size="xs"
                    onClick={() => openDebugChat(sessionRecordingId)}
                    loading={openingDebugChat || debugRecordingPreparing}
                    tooltip={debugRecordingPreparing ? PREPARING : debugChatTooltip(debugChatSummary)}
                    data-attr="replay-debug-chat-open"
                >
                    <IconSparkles />
                    Open debug chat
                </Button>
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                size="icon-xs"
                                aria-label="More debug options"
                                disabledReason={debugRecordingPreparing ? PREPARING : undefined}
                                data-attr="replay-debug-chat-more"
                            />
                        }
                    >
                        <IconChevronDown />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <DropdownMenuItem
                            onClick={() => setPromptModalOpen(true)}
                            data-attr="replay-debug-with-ai-again"
                        >
                            Debug again in a new chat
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </ButtonGroup>
            {promptModal}
        </>
    )
}
