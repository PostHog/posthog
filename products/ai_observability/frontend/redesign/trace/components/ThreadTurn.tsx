import { memo, useState } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { pluralize } from 'lib/utils/strings'

import { ConversationTurn, NodeSideContent, ThreadMessage } from '../types'
import { ChipButton } from './ChipButton'
import { conversationalSideMessages, sideHasContent, turnHasContent } from './conversationalMessages'
import { ErrorCallout } from './ErrorCallout'
import { compactStatParts } from './formatStats'
import { IOSection } from './IOSection'
import { NodeKindGlyph } from './NodeKindGlyph'
import { scrollIntoNearest } from './scrollIntoNearest'
import { ThreadBubble } from './ThreadBubble'
import { TurnSideMissingNotice } from './TurnSideMissingNotice'
import { TurnTiming } from './TurnTiming'

export interface ThreadTurnProps {
    turn: ConversationTurn
    isActive: boolean
    onSelectMessage: (sourceNodeId: string, turnId: string) => void
    /** The steps that contain the search query, or null when nothing is searched. */
    matchingNodeIds?: ReadonlySet<string> | null
    highlightQuery?: string | null
    showTiming?: boolean
    conversationOnly?: boolean
    /** Reads again the messages of turns whose read failed, for turns whose messages load after the turn. */
    onRetrySides?: () => void
}

const INTERNAL_ROLE_LABELS: Record<ThreadMessage['role'], string> = {
    system: 'system prompts',
    user: 'user messages',
    assistant: 'reasoning and tool calls',
    tool: 'tool results',
}

export const ThreadTurn = memo(function ThreadTurn({
    turn,
    isActive,
    onSelectMessage,
    matchingNodeIds = null,
    highlightQuery = null,
    showTiming = false,
    conversationOnly = false,
    onRetrySides,
}: ThreadTurnProps): JSX.Element {
    const [showInternal, setShowInternal] = useState(false)
    const turnClassName = cn('flex flex-col gap-3', isActive && 'rounded-lg p-3 ring-1 ring-[var(--color-accent)]')
    const timing = showTiming ? (
        <TurnTiming timestamp={turn.timestamp} waitMs={turn.waitMs} waitSlow={turn.waitSlow ?? false} />
    ) : null
    const errorCallout = turn.error ? <ErrorCallout message={turn.error} /> : null

    const hiddenMessages = [turn.input, turn.output]
        .flatMap(conversationalSideMessages)
        .filter((message) => message.isInternal)
    const hiddenRoles = [...new Set(hiddenMessages.map((message) => INTERNAL_ROLE_LABELS[message.role]))]
    const canShowInternal = showInternal && !conversationOnly
    const traceStats = turn.trace ? compactStatParts(turn.trace.totals).map((part) => part.text) : []
    const timedMessageId = showTiming
        ? (conversationalSideMessages(turn.input).find((message) => message.role === 'user' && !message.isInternal)
              ?.id ?? null)
        : null

    const renderSide = (title: string, side: NodeSideContent): JSX.Element | JSX.Element[] => {
        if (side.kind === 'json') {
            return <IOSection key={title} title={title} value={side.value} highlightQuery={highlightQuery} />
        }
        return conversationalSideMessages(side)
            .filter((message) => canShowInternal || !message.isInternal)
            .map((message) => {
                const sourceNodeId = message.sourceNodeId
                const isTimed = message.id === timedMessageId
                const bubble = (
                    <ThreadBubble
                        key={message.id}
                        message={message}
                        onSelect={sourceNodeId ? () => onSelectMessage(sourceNodeId, turn.id) : undefined}
                        isFaded={
                            matchingNodeIds !== null && sourceNodeId !== null && !matchingNodeIds.has(sourceNodeId)
                        }
                        highlightQuery={highlightQuery}
                        className={showTiming && message.role === 'user' ? 'max-w-[76%]' : undefined}
                    />
                )
                return isTimed ? (
                    // The timing sits in the room that the user bubble's narrower cap leaves on its left.
                    <div key={message.id} className="flex items-start justify-end gap-2">
                        {timing}
                        {bubble}
                    </div>
                ) : (
                    bubble
                )
            })
    }

    const renderMissing = (side: 'input' | 'output'): JSX.Element | null => {
        const reason = turn.missingReasons?.[side]
        if (!reason) {
            return null
        }
        const notice = (
            <TurnSideMissingNotice
                side={side}
                reason={reason}
                partial={sideHasContent(turn[side])}
                // A turn's id is its trace's, which is also the id of the trace's root step.
                onOpenTrace={() => onSelectMessage(turn.id, turn.id)}
            />
        )
        // With no user message to sit beside, the timing goes beside the notice.
        return side === 'input' && timing && timedMessageId === null ? (
            <div className="flex items-start justify-end gap-2">
                {timing}
                {notice}
            </div>
        ) : (
            notice
        )
    }

    const renderUnreadSides = (): JSX.Element | null => {
        if (turn.sidesStatus === 'loading') {
            return (
                <>
                    <div className="flex items-start justify-end gap-2">
                        {timing}
                        <LemonSkeleton className="h-9 w-1/2" />
                    </div>
                    <LemonSkeleton className="h-14 w-2/3" />
                </>
            )
        }
        const failed = turn.sidesStatus === 'error'
        const empty = turn.sidesStatus === 'ready' && !turnHasContent(turn) && !turn.missingReasons
        if (!failed && !empty) {
            return null
        }
        return (
            <div className="flex items-start justify-end gap-2">
                {timing}
                <div className="flex flex-wrap items-center gap-2 text-xs text-secondary">
                    {failed ? <IconWarning className="text-warning" /> : null}
                    <span>{failed ? "Couldn't load this turn's messages." : 'This turn has no messages to show.'}</span>
                    {failed && onRetrySides ? (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={onRetrySides}
                            data-attr="trace-view-thread-retry-turn-messages"
                        >
                            Retry
                        </LemonButton>
                    ) : null}
                    {empty ? (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => onSelectMessage(turn.id, turn.id)}
                            data-attr="trace-view-thread-open-empty-turn"
                        >
                            Open trace
                        </LemonButton>
                    ) : null}
                </div>
            </div>
        )
    }

    const unreadSides = renderUnreadSides()
    if (unreadSides) {
        return (
            <div className={turnClassName} ref={isActive ? scrollIntoNearest : undefined}>
                {unreadSides}
                {errorCallout}
            </div>
        )
    }

    return (
        <div className={turnClassName} ref={isActive ? scrollIntoNearest : undefined}>
            {hiddenMessages.length > 0 && !conversationOnly ? (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    className="self-center"
                    onClick={() => setShowInternal(!showInternal)}
                    data-attr="trace-view-toggle-hidden-messages"
                >
                    {canShowInternal ? (
                        'Hide internal messages'
                    ) : (
                        <>
                            <span>{`Show ${pluralize(hiddenMessages.length, 'internal message')}`}</span>
                            <span className="ml-1 font-normal text-tertiary">{`· ${hiddenRoles.join(', ')}`}</span>
                        </>
                    )}
                </LemonButton>
            ) : null}
            {renderSide('Input', turn.input)}
            {renderMissing('input')}
            {renderSide('Output', turn.output)}
            {renderMissing('output')}
            {errorCallout}
            {turn.trace?.name || traceStats.length > 0 ? (
                <div className="flex min-w-0">
                    <Tooltip title="Open trace">
                        <ChipButton
                            icon={<NodeKindGlyph kind="trace" />}
                            onClick={() => onSelectMessage(turn.id, turn.id)}
                            className="max-w-full min-w-0"
                            data-attr="trace-view-thread-open-turn-trace"
                        >
                            {/* The name is one the customer sets, so autocapture must not record it. */}
                            {turn.trace?.name ? (
                                <span className="ph-no-capture truncate" title={turn.trace.name}>
                                    {turn.trace.name}
                                </span>
                            ) : null}
                            {turn.trace?.name && traceStats.length > 0 ? (
                                <span className="shrink-0" aria-hidden>
                                    {' · '}
                                </span>
                            ) : null}
                            <span className="shrink-0">{traceStats.join(' · ')}</span>
                        </ChipButton>
                    </Tooltip>
                </div>
            ) : null}
        </div>
    )
})
