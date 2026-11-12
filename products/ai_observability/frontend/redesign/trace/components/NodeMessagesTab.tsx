import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'

import { IconMessage } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { MessagesOpening, NodeLoad, NodeSideContent } from '../types'
import { ErrorCallout } from './ErrorCallout'
import { firstOpenIndex } from './firstOpenIndex'
import { NodeContentGate } from './NodeContentGate'
import { NodeSideSection } from './NodeSideSection'
import { revealFirstOpenMessage } from './revealFirstOpenMessage'

export interface NodeMessagesTabProps {
    stepId: string
    load: NodeLoad
    onViewInThread: (() => void) | null
    opening: MessagesOpening
    onOpeningChange: (opening: MessagesOpening) => void
    highlightQuery?: string | null
}

export function NodeMessagesTab({
    stepId,
    load,
    onViewInThread,
    opening,
    onOpeningChange,
    highlightQuery = null,
}: NodeMessagesTabProps): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const inputIsMessages = load.status === 'ready' && load.node.content.input.kind === 'messages'
    const error = load.status === 'ready' ? load.node.error : null
    const isSearching = useRef(false)
    isSearching.current = !!highlightQuery
    const [resetCount, setResetCount] = useState(0)
    const listKey = `${opening}-${resetCount}`
    const previousListKey = useRef(listKey)
    // A new key remounts message sides, which drops what was opened or closed by hand. JSON sides keep their state.
    const sideKey = (id: string, side: 'input' | 'output', content: NodeSideContent): string =>
        content.kind === 'messages' ? `${id}-${side}-${listKey}` : `${id}-${side}`

    useEffect(() => {
        // A search scrolls to its own first highlight, which must win over the opening position.
        if (inputIsMessages && !isSearching.current) {
            revealFirstOpenMessage(containerRef.current, 'align')
        }
    }, [stepId, inputIsMessages])

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
            <NodeContentGate load={load}>
                {({ content: loaded }) => (
                    <>
                        {inputIsMessages ? (
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
                        ) : null}
                        <div
                            className={clsx(
                                'flex flex-col',
                                loaded.input.kind === 'json' && loaded.output.kind === 'json' ? 'gap-2' : 'gap-3'
                            )}
                        >
                            <NodeSideSection
                                key={sideKey(stepId, 'input', loaded.input)}
                                title="Input"
                                side={loaded.input}
                                emptyText="No input captured."
                                openFrom={
                                    loaded.input.kind === 'messages'
                                        ? firstOpenIndex(loaded.input.messages, opening)
                                        : 0
                                }
                                highlightQuery={highlightQuery}
                            />
                            <NodeSideSection
                                key={sideKey(stepId, 'output', loaded.output)}
                                title="Output"
                                side={loaded.output}
                                emptyText="No output captured."
                                openFrom={0}
                                highlightQuery={highlightQuery}
                            />
                        </div>
                        {onViewInThread ? (
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
                    </>
                )}
            </NodeContentGate>
        </div>
    )
}
