/**
 * Renders structured summary with collapsible sections
 */
import { useActions, useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { StructuredSummary, summaryViewLogic } from '../summaryViewLogic'
import { parseLineReferences } from '../utils/lineReferenceUtils'

export interface SummaryRendererProps {
    summary: StructuredSummary
    trace?: LLMTrace
    event?: LLMTraceEvent
    tree?: any[]
}

export function SummaryRenderer({ summary, trace, event, tree }: SummaryRendererProps): JSX.Element {
    const logic = summaryViewLogic({ trace, event, tree })
    const { isFlowExpanded, isSummaryExpanded, isNotesExpanded } = useValues(logic)
    const { toggleFlowExpanded, toggleSummaryExpanded, toggleNotesExpanded } = useActions(logic)

    const renderLineRefs = (lineRefs: string): JSX.Element | null => {
        if (!lineRefs || lineRefs.trim() === '') {
            return null
        }
        return <span className="ml-2">{parseLineReferences(lineRefs)}</span>
    }

    return (
        <div className="space-y-4">
            {/* Title */}
            <h3 className="text-lg font-semibold">{summary.title}</h3>

            {/* Flow Diagram - Collapsible ASCII */}
            <div className="border border-border rounded">
                <Tooltip title="ASCII diagram showing the main steps and flow of execution">
                    <button
                        type="button"
                        className="w-full text-left px-3 py-2 font-medium flex items-center gap-2 hover:bg-accent text-sm"
                        onClick={toggleFlowExpanded}
                        data-attr="summary-toggle-flow-diagram"
                    >
                        <span className="text-xs">{isFlowExpanded ? '▼' : '▶'}</span>
                        Flow Diagram
                    </button>
                </Tooltip>
                {isFlowExpanded && (
                    <div className="px-3 py-2 border-t border-border bg-bg-light">
                        <pre className="font-mono text-sm whitespace-pre overflow-x-auto m-0">
                            {summary.flow_diagram}
                        </pre>
                    </div>
                )}
            </div>

            {/* Summary Bullets - Collapsible */}
            <div className="border border-border rounded">
                <Tooltip title="Key highlights and main actions from this trace or event">
                    <button
                        type="button"
                        className="w-full text-left px-3 py-2 font-medium flex items-center gap-2 hover:bg-accent text-sm"
                        onClick={toggleSummaryExpanded}
                        data-attr="summary-toggle-points"
                    >
                        <span className="text-xs">{isSummaryExpanded ? '▼' : '▶'}</span>
                        Summary Points
                    </button>
                </Tooltip>
                {isSummaryExpanded && (
                    <div className="px-3 py-2 border-t border-border bg-bg-light">
                        <ul className="list-disc list-inside space-y-1">
                            {summary.summary_bullets.map((bullet, idx) => (
                                <li key={idx} className="text-sm">
                                    {bullet.text}
                                    {renderLineRefs(bullet.line_refs)}
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </div>

            {/* Interesting Notes - Collapsible (if present) */}
            {summary.interesting_notes.length > 0 && (
                <div className="border border-border rounded">
                    <Tooltip title="Notable observations like errors, unusual patterns, or important details">
                        <button
                            type="button"
                            className="w-full text-left px-3 py-2 font-medium flex items-center gap-2 hover:bg-accent text-sm"
                            onClick={toggleNotesExpanded}
                            data-attr="summary-toggle-notes"
                        >
                            <span className="text-xs">{isNotesExpanded ? '▼' : '▶'}</span>
                            Interesting Notes
                        </button>
                    </Tooltip>
                    {isNotesExpanded && (
                        <div className="px-3 py-2 border-t border-border bg-bg-light">
                            <ul className="list-disc list-inside space-y-1">
                                {summary.interesting_notes.map((note, idx) => (
                                    <li key={idx} className="text-sm">
                                        {note.text}
                                        {renderLineRefs(note.line_refs)}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
