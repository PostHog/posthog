import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import { LemonModal, LemonTag, Spinner } from '@posthog/lemon-ui'

import { CollapsibleContent } from 'products/tasks/frontend/components/CollapsibleContent'
import { ConsoleLogEntry } from 'products/tasks/frontend/components/session/ConsoleLogEntry'
import { ToolCallEntry } from 'products/tasks/frontend/components/session/ToolCallEntry'
import { mergeDuplicateUserPromptEntries } from 'products/tasks/frontend/components/TaskSessionView'
import { LogEntry } from 'products/tasks/frontend/lib/parse-logs'

import { detectFlowsLogic } from './detectFlowsLogic'

function LogEntryRow({ entry }: { entry: LogEntry }): JSX.Element | null {
    switch (entry.type) {
        case 'console':
            return (
                <ConsoleLogEntry
                    level={entry.level || 'info'}
                    message={entry.message || ''}
                    timestamp={entry.timestamp}
                />
            )
        case 'tool':
            return (
                <ToolCallEntry
                    toolName={entry.toolName || 'unknown'}
                    status={entry.toolStatus || 'pending'}
                    args={entry.toolArgs}
                    result={entry.toolResult}
                    timestamp={entry.timestamp}
                />
            )
        case 'agent':
            return (
                <div className="py-2">
                    <div className="flex items-center gap-2 mb-1">
                        {entry.timestamp && (
                            <span className="text-xs text-muted">{new Date(entry.timestamp).toLocaleTimeString()}</span>
                        )}
                        <span className="text-xs font-medium">Agent</span>
                    </div>
                    <div className="border-l-2 border-primary pl-3 max-w-[90%]">
                        <div className="text-sm whitespace-pre-wrap">{entry.message}</div>
                    </div>
                </div>
            )
        case 'thinking':
            return (
                <div className="py-2">
                    <div className="flex items-center gap-2 mb-1">
                        {entry.timestamp && (
                            <span className="text-xs text-muted">{new Date(entry.timestamp).toLocaleTimeString()}</span>
                        )}
                        <span className="text-xs font-medium text-muted">Thinking</span>
                    </div>
                    <div className="border-l-2 border-muted pl-3 max-w-[90%]">
                        <CollapsibleContent gradientColor="--bg-3000">
                            <div className="text-sm whitespace-pre-wrap text-muted">{entry.message}</div>
                        </CollapsibleContent>
                    </div>
                </div>
            )
        case 'system':
            return (
                <div className="flex items-center gap-2 py-1">
                    {entry.timestamp && (
                        <span className="text-xs text-muted">{new Date(entry.timestamp).toLocaleTimeString()}</span>
                    )}
                    <span className="text-xs text-muted italic">{entry.message}</span>
                </div>
            )
        case 'raw':
            return <div className="py-0.5 text-xs font-mono text-muted break-all">{entry.raw}</div>
        default:
            return null
    }
}

export function DetectFlowsLogsModal(): JSX.Element {
    const { logsModalOpen, streamEntries, isTerminal, step } = useValues(detectFlowsLogic)
    const { closeLogsModal } = useActions(detectFlowsLogic)

    const scrollRef = useRef<HTMLDivElement>(null)
    const [isUserScrolledUp, setIsUserScrolledUp] = useState(false)

    const entries = useMemo(() => mergeDuplicateUserPromptEntries(streamEntries), [streamEntries])

    useEffect(() => {
        const el = scrollRef.current
        if (el && !isUserScrolledUp) {
            el.scrollTop = el.scrollHeight
        }
    }, [entries.length, isUserScrolledUp])

    const handleScroll = (): void => {
        const el = scrollRef.current
        if (!el) {
            return
        }
        const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
        setIsUserScrolledUp(!nearBottom)
    }

    const stepLabels = ['Setting up', 'Analyzing product', 'Complete']

    return (
        <LemonModal
            isOpen={logsModalOpen}
            onClose={closeLogsModal}
            title={
                <div className="flex items-center gap-2">
                    {!isTerminal && <Spinner />}
                    <span>{isTerminal ? 'Flow detection complete' : 'Auto-detecting flows...'}</span>
                    {!isTerminal && (
                        <LemonTag type="muted" size="small">
                            {stepLabels[step - 1]}
                        </LemonTag>
                    )}
                </div>
            }
            width="min(90vw, 1100px)"
        >
            <div
                ref={scrollRef}
                onScroll={handleScroll}
                className="h-[75vh] overflow-auto -mx-6 -mb-6 px-4 py-2 font-mono text-sm bg-bg-3000"
            >
                {entries.length === 0 ? (
                    <div className="flex items-center justify-center h-full text-muted">
                        {isTerminal ? 'Logs are no longer available for this run.' : 'Waiting for agent to start...'}
                    </div>
                ) : (
                    entries.map((entry) => <LogEntryRow key={entry.id} entry={entry} />)
                )}
            </div>
        </LemonModal>
    )
}
