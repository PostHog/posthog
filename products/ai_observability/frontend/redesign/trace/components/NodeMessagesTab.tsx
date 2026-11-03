import { useEffect, useRef, useState } from 'react'

import { IconMessage } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { MessagesOpening, NodeContent } from '../types'
import { ErrorCallout } from './ErrorCallout'
import { firstOpenIndex } from './firstOpenIndex'
import { IOPanel } from './IOPanel'
import { MessageSection } from './MessageSection'
import { revealFirstOpenMessage } from './revealFirstOpenMessage'

export interface NodeMessagesTabProps {
    stepId: string
    content: NodeContent
    error: string | null
    onViewInThread: (() => void) | null
    opening: MessagesOpening
    onOpeningChange: (opening: MessagesOpening) => void
    highlightQuery?: string | null
}

export function NodeMessagesTab({
    stepId,
    content,
    error,
    onViewInThread,
    opening,
    onOpeningChange,
    highlightQuery = null,
}: NodeMessagesTabProps): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const hasMessages = content.kind === 'messages'
    const isSearching = useRef(false)
    isSearching.current = !!highlightQuery
    const [resetCount, setResetCount] = useState(0)
    const listKey = `${opening}-${resetCount}`
    const previousListKey = useRef(listKey)

    useEffect(() => {
        // A search scrolls to its own first highlight, which must win over the opening position.
        if (hasMessages && !isSearching.current) {
            revealFirstOpenMessage(containerRef.current, 'align')
        }
    }, [stepId, hasMessages])

    useEffect(() => {
        if (previousListKey.current !== listKey && opening === 'lastTurn') {
            revealFirstOpenMessage(containerRef.current, 'ifBelow')
        }
        previousListKey.current = listKey
    }, [listKey, opening])

    const selectOpening = (value: MessagesOpening): void => {
        if (value === opening) {
            setResetCount(resetCount + 1)
        } else {
            onOpeningChange(value)
        }
    }
    const tooltip = (value: MessagesOpening, description: string): string =>
        value === opening ? `${description}. Click again to reset this step.` : description

    return (
        <div className="flex flex-col gap-3" ref={containerRef}>
            {error ? <ErrorCallout message={error} /> : null}
            {content.kind === 'loading' ? (
                <LemonSkeleton repeat={3} className="h-16" />
            ) : content.kind === 'error' ? (
                <ErrorCallout message={content.message} />
            ) : content.kind === 'messages' ? (
                <>
                    <div className="flex justify-end">
                        <LemonSegmentedButton
                            size="xsmall"
                            value={opening}
                            onChange={selectOpening}
                            data-attr="trace-view-messages-opening"
                            options={[
                                {
                                    value: 'lastTurn',
                                    label: 'Last turn',
                                    tooltip: tooltip('lastTurn', 'Open messages from the last user message on'),
                                    'data-attr': 'trace-view-messages-opening-last-turn',
                                },
                                {
                                    value: 'everything',
                                    label: 'Everything',
                                    tooltip: tooltip('everything', 'Open every message'),
                                    'data-attr': 'trace-view-messages-opening-everything',
                                },
                            ]}
                        />
                    </div>
                    {/* A new key remounts the messages, which drops what was opened or closed by hand. */}
                    <div key={listKey} className="flex flex-col gap-3">
                        <MessageSection
                            title="Input"
                            messages={content.input}
                            emptyText="No input captured."
                            openFrom={firstOpenIndex(content.input, opening)}
                            highlightQuery={highlightQuery}
                        />
                        <MessageSection
                            title="Output"
                            messages={content.output}
                            emptyText="No output captured."
                            openFrom={0}
                            highlightQuery={highlightQuery}
                        />
                    </div>
                </>
            ) : (
                <IOPanel input={content.input} output={content.output} />
            )}
            {onViewInThread && content.kind !== 'loading' ? (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconMessage />}
                    className="self-start"
                    onClick={onViewInThread}
                    data-attr="trace-view-view-in-thread"
                >
                    View in thread
                </LemonButton>
            ) : null}
        </div>
    )
}
