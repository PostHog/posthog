import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useState } from 'react'

import { IconBook, IconTerminal, IconWarning } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonTag } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import {
    getNotebookAgentColorIndex,
    getNotebookAgentEmoji,
    getNotebookAgentSyntheticUserId,
    getNotebookAgentsFromMarkdown,
    removeNotebookAgentFromMarkdown,
} from 'lib/components/MarkdownNotebook/notebookAgents'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconDocumentExpand } from 'lib/lemon-ui/icons'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { userLogic } from 'scenes/userLogic'

import { NotebookSyncStatus } from '../types'
import { notebookCollabLogic } from './notebookCollabLogic'
import { NotebookLogicProps, notebookLogic } from './notebookLogic'
import {
    getNotebookPresenceParticipants,
    type NotebookPresenceParticipant,
    type NotebookRemoteParticipant,
} from './notebookPresence'
import { notebookSettingsLogic } from './notebookSettingsLogic'

const MAX_PRESENCE_BUBBLES = 6

const syncStatusMap: Record<NotebookSyncStatus, { content: React.ReactNode; tooltip: React.ReactNode }> = {
    synced: {
        content: 'Saved',
        tooltip: 'All changes are saved.',
    },
    saving: {
        content: (
            <>
                Saving <Spinner textColored />
            </>
        ),
        tooltip: 'The changes are being saved to PostHog.',
    },
    unsaved: {
        content: 'Edited',
        tooltip:
            'You have made changes that are saved to your browser. These will be persisted to PostHog periodically.',
    },
    local: {
        content: 'Local',
        tooltip: 'This notebook is just stored in your browser.',
    },
}

export const NotebookSyncInfo = (props: NotebookLogicProps): JSX.Element | null => {
    const { syncStatus } = useValues(notebookLogic(props))
    const [shown, setShown] = useState(false)
    const [debounceTimeout, setDebounceTimeout] = useState<NodeJS.Timeout | null>(null)
    const [debouncedSyncStatus, setDebouncedSyncStatus] = useState<NotebookSyncStatus | null>(null)

    const clearDebounceTimeout = useCallback(() => {
        if (debounceTimeout) {
            clearTimeout(debounceTimeout)
        }
    }, [debounceTimeout])

    useEffect(() => {
        clearDebounceTimeout()

        const debounceDelay = syncStatus === 'saving' ? 100 : 0
        const timeout = setTimeout(() => setDebouncedSyncStatus(syncStatus), debounceDelay)
        setDebounceTimeout(timeout)

        if (syncStatus !== 'synced') {
            return setShown(true)
        }

        if (shown === false) {
            return
        }

        const t = setTimeout(() => setShown(false), 3000)

        return () => {
            clearTimeout(t)
            clearDebounceTimeout()
        }
        // oxlint-disable-next-line exhaustive-deps
    }, [syncStatus])

    if (!debouncedSyncStatus) {
        return null
    }

    const content = syncStatusMap[debouncedSyncStatus]

    return shown ? (
        <Tooltip title={content.tooltip} placement="left">
            <LemonTag className="uppercase select-none">{content.content}</LemonTag>
        </Tooltip>
    ) : null
}

/**
 * Surfaces when the collab SSE is disconnected *and* no reconnect attempt is in flight,
 * so the user only sees the warning when something is actually wrong — not during the
 * initial connect or the brief gap on a normal reconnect.
 */
export const NotebookCollabStatus = (props: NotebookLogicProps): JSX.Element | null => {
    const { collabEnabled } = useValues(notebookLogic(props))
    const { streamConnected, isConnecting, streamError } = useValues(notebookCollabLogic({ shortId: props.shortId }))

    if (!collabEnabled || streamConnected || isConnecting) {
        return null
    }

    const tooltip = streamError ? `Live updates paused. Last error: ${streamError}` : 'Live updates paused.'

    return (
        <Tooltip title={tooltip} placement="left">
            <LemonButton size="small" icon={<IconWarning className="text-warning" />} type="tertiary" />
        </Tooltip>
    )
}

function notebookPresenceTooltip(participants: NotebookPresenceParticipant[]): string {
    const visibleNames = participants.slice(0, MAX_PRESENCE_BUBBLES).map((participant) => participant.userName)
    const overflowCount = participants.length - visibleNames.length
    const names =
        overflowCount > 0
            ? `${formatNotebookPresenceNames(visibleNames)} and ${overflowCount} more`
            : formatNotebookPresenceNames(visibleNames)
    const verb = participants.length === 1 && !participants[0].isCurrentUser ? 'is' : 'are'
    return `${names} ${verb} viewing this notebook`
}

function formatNotebookPresenceNames(names: string[]): string {
    if (names.length <= 1) {
        return names[0] ?? ''
    }
    if (names.length === 2) {
        return `${names[0]} and ${names[1]}`
    }
    return `${names.slice(0, -1).join(', ')}, and ${names[names.length - 1]}`
}

export const NotebookPresence = (props: NotebookLogicProps): JSX.Element | null => {
    const { user } = useValues(userLogic)
    const { isEditable, markdownEditorValue, markdownRemoteParticipants } = useValues(
        notebookLogic(props)
    ) as unknown as {
        isEditable: boolean
        markdownEditorValue: string
        markdownRemoteParticipants: NotebookRemoteParticipant[]
    }
    const { handleMarkdownEditorChange } = useActions(notebookLogic(props))
    const { remoteParticipants } = useValues(notebookCollabLogic({ shortId: props.shortId })) as unknown as {
        remoteParticipants: NotebookRemoteParticipant[]
    }
    const humanParticipants = getNotebookPresenceParticipants(
        user,
        markdownRemoteParticipants.length > 0 ? markdownRemoteParticipants : remoteParticipants
    )
    const notebookAgents = getNotebookAgentsFromMarkdown(markdownEditorValue)
    const agentParticipants: NotebookPresenceParticipant[] = notebookAgents.map((agent) => ({
        clientId: `agent-${agent.id}`,
        userId: getNotebookAgentSyntheticUserId(agent),
        userName: agent.name,
        lastSeenAt: Date.now(),
        isAgent: true,
        agentId: agent.id,
    }))
    const participants = [...humanParticipants, ...agentParticipants]

    if (!participants.length) {
        return null
    }

    const shownParticipants = participants.slice(0, MAX_PRESENCE_BUBBLES)
    const overflowCount = participants.length - shownParticipants.length
    const overflowTitle =
        overflowCount > 0
            ? participants
                  .slice(MAX_PRESENCE_BUBBLES)
                  .map((participant) => participant.userName)
                  .join(', ')
            : undefined
    const tooltip = notebookPresenceTooltip(participants)
    const removeAgent = (agentId: string): void => {
        if (!isEditable) {
            return
        }
        handleMarkdownEditorChange(removeNotebookAgentFromMarkdown(markdownEditorValue, agentId))
    }

    return (
        <Tooltip title={tooltip} placement="left">
            <div className="ProfileBubbles" aria-label={tooltip}>
                {shownParticipants.map((participant) =>
                    participant.isAgent && participant.agentId ? (
                        <button
                            key={`${participant.userId}-${participant.clientId}`}
                            className="NotebookPresence__agent-bubble"
                            type="button"
                            title={isEditable ? `Remove ${participant.userName}` : participant.userName}
                            aria-label={isEditable ? `Remove ${participant.userName}` : participant.userName}
                            style={
                                {
                                    '--notebook-agent-color': getSeriesColor(
                                        getNotebookAgentColorIndex({ id: participant.agentId })
                                    ),
                                } as React.CSSProperties
                            }
                            onClick={() => removeAgent(participant.agentId as string)}
                            disabled={!isEditable}
                        >
                            {getNotebookAgentEmoji({ name: participant.userName })}
                        </button>
                    ) : (
                        <ProfilePicture
                            key={`${participant.userId}-${participant.clientId}`}
                            user={participant.profileUser}
                            name={participant.userName}
                            title={participant.userName}
                            size="md"
                            index={participant.userId}
                        />
                    )
                )}
                {overflowCount > 0 ? (
                    <div className="ProfileBubbles__more" title={overflowTitle}>
                        +{overflowCount}
                    </div>
                ) : null}
            </div>
        </Tooltip>
    )
}

interface NotebookExpandButtonProps extends Pick<LemonButtonProps, 'size' | 'type'> {
    inPanel: boolean
}

export const NotebookExpandButton = (props: NotebookExpandButtonProps): JSX.Element => {
    const { isExpanded } = useValues(notebookSettingsLogic)
    const { setIsExpanded } = useActions(notebookSettingsLogic)

    if (props.inPanel) {
        return (
            <ButtonPrimitive
                onClick={() => setIsExpanded(!isExpanded)}
                iconOnly
                tooltip={isExpanded ? 'Fix content width' : 'Fill content width'}
                tooltipPlacement="left"
            >
                <IconDocumentExpand
                    className="text-tertiary size-4 group-hover:text-primary z-10"
                    mode={isExpanded ? 'expand' : 'collapse'}
                />
            </ButtonPrimitive>
        )
    }
    return (
        <LemonButton
            {...props}
            onClick={() => setIsExpanded(!isExpanded)}
            icon={<IconDocumentExpand mode={isExpanded ? 'expand' : 'collapse'} />}
            tooltip={isExpanded ? 'Fix content width' : 'Fill content width'}
            tooltipPlacement="left"
        />
    )
}

export const NotebookTableOfContentsButton = (props: Pick<LemonButtonProps, 'size' | 'type'>): JSX.Element => {
    const { showTableOfContents } = useValues(notebookSettingsLogic)
    const { setShowTableOfContents } = useActions(notebookSettingsLogic)

    return (
        <LemonButton
            {...props}
            onClick={() => setShowTableOfContents(!showTableOfContents)}
            icon={<IconBook />}
            tooltip={showTableOfContents ? 'Hide table of contents' : 'Show table of contents'}
            tooltipPlacement="left"
        />
    )
}

export const NotebookKernelInfoButton = (props: Pick<LemonButtonProps, 'size' | 'type'>): JSX.Element | null => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { showKernelInfo } = useValues(notebookSettingsLogic)
    const { setShowKernelInfo } = useActions(notebookSettingsLogic)

    if (!featureFlags[FEATURE_FLAGS.NOTEBOOK_PYTHON]) {
        return null
    }

    return (
        <LemonButton
            {...props}
            onClick={() => setShowKernelInfo(!showKernelInfo)}
            icon={<IconTerminal />}
            tooltip={showKernelInfo ? 'Hide kernel info' : 'Show kernel info'}
            tooltipPlacement="left"
        />
    )
}
