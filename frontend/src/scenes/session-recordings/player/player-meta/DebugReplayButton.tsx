import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconChevronDown, IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { SettingsButton } from 'lib/components/PanelSettings/PanelSettings'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { isTerminalRunStatus, useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { DebugChatSummary, debugReplayChatLogic } from './debugReplayChatLogic'
import { buildDebugReplayContextItems } from './debugReplayPrompt'
import { DebugReplayPromptModal } from './DebugReplayPromptModal'

function debugChatTooltip(debugChatSummary: DebugChatSummary | undefined): JSX.Element | string {
    if (debugChatSummary?.summary) {
        return (
            <div className="space-y-1">
                <div className="max-h-80 overflow-y-auto whitespace-pre-line">{debugChatSummary.summary}</div>
                <div className="text-xs text-tertiary">Click to open the chat.</div>
            </div>
        )
    }
    if (debugChatSummary && !isTerminalRunStatus(debugChatSummary.runStatus)) {
        return 'PostHog AI is still debugging this recording. Click to open the chat.'
    }
    return 'Opens the PostHog AI chat that debugged this recording.'
}

export function DebugReplayButton({ settingsBar = false }: { settingsBar?: boolean }): JSX.Element {
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
    const preparingTooltip = 'Loading the recording data for PostHog AI'

    useEffect(() => {
        if (hasDebugChat && !debugChatSummary) {
            loadDebugChatSummary(sessionRecordingId)
        }
    }, [hasDebugChat, debugChatSummary, sessionRecordingId, loadDebugChatSummary])

    const promptModal = promptModalOpen ? <DebugReplayPromptModal onClose={() => setPromptModalOpen(false)} /> : null

    if (hasDebugChat) {
        const openProps = {
            icon: <IconSparkles />,
            onClick: () => openDebugChat(sessionRecordingId),
            loading: openingDebugChat || debugRecordingPreparing,
            tooltip: debugRecordingPreparing ? preparingTooltip : debugChatTooltip(debugChatSummary),
            'data-attr': 'replay-debug-chat-open',
            sideAction: {
                icon: <IconChevronDown />,
                dropdown: {
                    placement: 'bottom-end' as const,
                    overlay: (
                        <LemonMenuOverlay
                            items={[
                                {
                                    label: 'Debug again in a new chat',
                                    onClick: () => setPromptModalOpen(true),
                                    'data-attr': 'replay-debug-with-ai-again',
                                },
                            ]}
                        />
                    ),
                },
                divider: false,
                disabledReason: debugRecordingPreparing ? preparingTooltip : null,
                'aria-label': 'More debug options',
                'data-attr': 'replay-debug-chat-more',
            },
        }
        return (
            <>
                {settingsBar ? (
                    <SettingsButton label="Open debug chat" {...openProps} />
                ) : (
                    <LemonButton size="small" type="secondary" className="shrink-0" {...openProps}>
                        Open debug chat
                    </LemonButton>
                )}
                {promptModal}
            </>
        )
    }

    const startProps = {
        icon: <IconSparkles />,
        onClick: () => setPromptModalOpen(true),
        loading: debugRecordingPreparing,
        tooltip: debugRecordingPreparing
            ? preparingTooltip
            : 'Asks PostHog AI what went wrong in this recording. You can edit the prompt first.',
        'data-attr': 'replay-debug-with-ai',
    }
    return (
        <>
            {settingsBar ? (
                <SettingsButton label="Debug this replay" {...startProps} />
            ) : (
                <LemonButton size="small" type="secondary" className="shrink-0" {...startProps}>
                    Debug this replay
                </LemonButton>
            )}
            {promptModal}
        </>
    )
}
