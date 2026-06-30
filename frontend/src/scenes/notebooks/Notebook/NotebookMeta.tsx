import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useState } from 'react'

import { IconBook, IconSparkles, IconTerminal, IconWarning } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonTag } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconDocumentExpand } from 'lib/lemon-ui/icons'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { NotebookSyncStatus } from '../types'
import { notebookCollabLogic } from './notebookCollabLogic'
import { NotebookLogicProps, notebookLogic } from './notebookLogic'
import { NOTEBOOK_AI_PRESENCE_COLOR, type NotebookPresenceParticipant } from './notebookPresence'
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
    const { notebookPresenceParticipants: participants } = useValues(notebookLogic(props))

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
    return (
        <Tooltip title={tooltip} placement="left">
            <div className="ProfileBubbles" aria-label={tooltip}>
                {shownParticipants.map((participant) =>
                    participant.isAI ? (
                        <div
                            key={`${participant.userId}-${participant.clientId}`}
                            className="NotebookPresence__ai-bubble"
                            title={participant.userName}
                            aria-label={participant.userName}
                            style={
                                {
                                    '--notebook-ai-presence-color': NOTEBOOK_AI_PRESENCE_COLOR,
                                } as React.CSSProperties
                            }
                        >
                            <IconSparkles className="size-3" />
                        </div>
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
    isMarkdownNotebook?: boolean
}

export const NotebookExpandButton = ({
    inPanel,
    isMarkdownNotebook = false,
    ...buttonProps
}: NotebookExpandButtonProps): JSX.Element => {
    const { isExpanded, isMarkdownExpanded } = useValues(notebookSettingsLogic)
    const { setIsExpanded, setIsMarkdownExpanded } = useActions(notebookSettingsLogic)
    const isContentWidthExpanded = isMarkdownNotebook ? isMarkdownExpanded : isExpanded
    const toggleContentWidth = (): void => {
        const nextIsExpanded = !isContentWidthExpanded
        if (isMarkdownNotebook) {
            setIsMarkdownExpanded(nextIsExpanded)
        } else {
            setIsExpanded(nextIsExpanded)
        }
    }

    if (inPanel) {
        return (
            <ButtonPrimitive
                onClick={toggleContentWidth}
                iconOnly
                tooltip={isContentWidthExpanded ? 'Fix content width' : 'Fill content width'}
                tooltipPlacement="left"
            >
                <IconDocumentExpand
                    className="text-tertiary size-4 group-hover:text-primary z-10"
                    mode={isContentWidthExpanded ? 'expand' : 'collapse'}
                />
            </ButtonPrimitive>
        )
    }
    return (
        <LemonButton
            {...buttonProps}
            onClick={toggleContentWidth}
            icon={<IconDocumentExpand mode={isContentWidthExpanded ? 'expand' : 'collapse'} />}
            tooltip={isContentWidthExpanded ? 'Fix content width' : 'Fill content width'}
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

type NotebookKernelInfoButtonProps = Pick<LemonButtonProps, 'children' | 'size' | 'type'> & {
    onBeforeShowKernelInfo?: () => void
}

export const NotebookKernelInfoButton = ({
    onBeforeShowKernelInfo,
    ...props
}: NotebookKernelInfoButtonProps): JSX.Element | null => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { showKernelInfo } = useValues(notebookSettingsLogic)
    const { setShowKernelInfo } = useActions(notebookSettingsLogic)

    if (!featureFlags[FEATURE_FLAGS.NOTEBOOK_PYTHON]) {
        return null
    }

    return (
        <LemonButton
            {...props}
            onClick={() => {
                const nextShowKernelInfo = !showKernelInfo
                if (nextShowKernelInfo) {
                    onBeforeShowKernelInfo?.()
                }
                setShowKernelInfo(nextShowKernelInfo)
            }}
            active={showKernelInfo}
            icon={<IconTerminal />}
            tooltip={showKernelInfo ? 'Hide kernel info' : 'Show kernel info'}
            tooltipPlacement="left"
        />
    )
}
