import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconChevronDown, IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { debugReplayChatLogic } from './debugReplayChatLogic'
import { buildDebugReplayContextItems } from './debugReplayPrompt'

export function DebugReplayButton(): JSX.Element {
    const { sessionRecordingId, debugRecordingPreparing } = useValues(sessionRecordingPlayerLogic)
    const { debugRecordingWithAI } = useActions(sessionRecordingPlayerLogic)
    const { taskIdBySessionRecordingId, openingSessionRecordingId } = useValues(debugReplayChatLogic)
    const { openDebugChat } = useActions(debugReplayChatLogic)

    const contextItems = useMemo(() => buildDebugReplayContextItems(sessionRecordingId), [sessionRecordingId])
    useAttachedContext(contextItems)

    const hasDebugChat = !!taskIdBySessionRecordingId[sessionRecordingId]
    const openingDebugChat = openingSessionRecordingId === sessionRecordingId
    const preparingTooltip = 'Loading the recording data for PostHog AI'

    if (hasDebugChat) {
        return (
            <LemonButton
                size="small"
                type="secondary"
                className="shrink-0"
                icon={<IconSparkles />}
                onClick={() => openDebugChat(sessionRecordingId)}
                loading={openingDebugChat || debugRecordingPreparing}
                tooltip={
                    debugRecordingPreparing
                        ? preparingTooltip
                        : 'Opens the PostHog AI chat that debugged this recording.'
                }
                data-attr="replay-debug-chat-open"
                sideAction={{
                    icon: <IconChevronDown />,
                    dropdown: {
                        placement: 'bottom-end',
                        overlay: (
                            <LemonMenuOverlay
                                items={[
                                    {
                                        label: 'Debug again in a new chat',
                                        onClick: debugRecordingWithAI,
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
                }}
            >
                Open debug chat
            </LemonButton>
        )
    }

    return (
        <LemonButton
            size="small"
            type="secondary"
            className="shrink-0"
            icon={<IconSparkles />}
            onClick={debugRecordingWithAI}
            loading={debugRecordingPreparing}
            tooltip={
                debugRecordingPreparing
                    ? preparingTooltip
                    : 'Sends the recording JSON to PostHog AI and asks what went wrong.'
            }
            data-attr="replay-debug-with-ai"
        >
            Debug this replay
        </LemonButton>
    )
}
