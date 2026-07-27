/**
 * Component for rendering nested content that may contain truncated segments
 * Used for expandable sections within the main text view
 */
import { IconExternal } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { VISIBLE_TOOLS_COUNT } from '../constants'
import { parseTruncatedSegments } from '../parsing'
import { TextWithLinks } from './TextWithLinks'

interface NestedContentRendererProps {
    content: string
    traceId?: string
    parentKey: string
    expandedSegments: Set<number | string>
    setExpandedSegments: (segments: Set<number | string>) => void
    popoutSegment: number | string | null
    setPopoutSegment: (index: number | string | null) => void
    activeLineNumber?: number | null
    lineNumberPadding?: number
    onCopyPermalink?: (lineNumber: number) => void
    enableLineActions?: boolean
}

export function NestedContentRenderer({
    content,
    traceId,
    parentKey,
    expandedSegments,
    setExpandedSegments,
    popoutSegment,
    setPopoutSegment,
    activeLineNumber,
    lineNumberPadding,
    onCopyPermalink,
    enableLineActions = false,
}: NestedContentRendererProps): JSX.Element {
    const nestedSegments = parseTruncatedSegments(content)

    const toggleNestedSegment = (nestedIndex: number): void => {
        const key = `${parentKey}-${nestedIndex}`
        const next = new Set(expandedSegments)
        if (next.has(key)) {
            next.delete(key)
        } else {
            next.add(key)
        }
        setExpandedSegments(next)
    }

    const toggleNestedPopout = (nestedIndex: number): void => {
        const key = `${parentKey}-${nestedIndex}`
        setPopoutSegment(popoutSegment === key ? null : key)
    }

    return (
        <>
            {nestedSegments.map((nestedSeg, nestedIdx) => {
                const nestedKey = `${parentKey}-${nestedIdx}`
                const isNestedExpanded = expandedSegments.has(nestedKey)
                const isNestedPopoutOpen = popoutSegment === nestedKey

                if (nestedSeg.type === 'text') {
                    return (
                        <span key={nestedIdx}>
                            <TextWithLinks
                                text={nestedSeg.content}
                                traceId={traceId}
                                activeLineNumber={activeLineNumber}
                                lineNumberPadding={lineNumberPadding}
                                onCopyPermalink={onCopyPermalink}
                                enableLineActions={enableLineActions}
                            />
                        </span>
                    )
                }

                if (nestedSeg.type === 'tools_expandable') {
                    // Parse full content to split into individual tools
                    const fullContent = nestedSeg.fullContent || ''
                    const lines = fullContent.split('\n')

                    // Find header line (e.g., "AVAILABLE TOOLS: 10")
                    const headerLine = lines[0]
                    const toolLines = lines.slice(1) // Skip header

                    // Parse individual tool blocks
                    const toolBlocks: string[] = []
                    let currentBlock: string[] = []

                    for (const line of toolLines) {
                        if (line.trim() === '' && currentBlock.length > 0) {
                            toolBlocks.push(currentBlock.join('\n'))
                            currentBlock = []
                        } else if (line.trim() !== '') {
                            currentBlock.push(line)
                        }
                    }
                    if (currentBlock.length > 0) {
                        toolBlocks.push(currentBlock.join('\n'))
                    }

                    // Split into visible and remaining tools
                    const visibleTools = toolBlocks.slice(0, VISIBLE_TOOLS_COUNT)
                    const hiddenTools = toolBlocks.slice(VISIBLE_TOOLS_COUNT)

                    return (
                        <span key={nestedIdx}>
                            {headerLine}
                            {'\n\n'}
                            {visibleTools.map((toolBlock, i) => (
                                <span key={i}>
                                    <TextWithLinks
                                        text={toolBlock}
                                        traceId={traceId}
                                        activeLineNumber={activeLineNumber}
                                        lineNumberPadding={lineNumberPadding}
                                        onCopyPermalink={onCopyPermalink}
                                        enableLineActions={enableLineActions}
                                    />
                                    {'\n\n'}
                                </span>
                            ))}
                            {hiddenTools.length > 0 && (
                                <>
                                    <button
                                        onClick={() => toggleNestedSegment(nestedIdx)}
                                        className="text-link hover:underline cursor-pointer"
                                        title={isNestedExpanded ? 'Collapse' : 'Expand'}
                                    >
                                        {isNestedExpanded ? '[−]' : '[+]'} {hiddenTools.length} more tool
                                        {hiddenTools.length > 1 ? 's' : ''}
                                    </button>
                                    {isNestedExpanded && (
                                        <div className="ml-4 mt-2 mb-2">
                                            {hiddenTools.map((toolBlock, i) => (
                                                <span key={i}>
                                                    <TextWithLinks
                                                        text={toolBlock}
                                                        traceId={traceId}
                                                        activeLineNumber={activeLineNumber}
                                                        lineNumberPadding={lineNumberPadding}
                                                        onCopyPermalink={onCopyPermalink}
                                                        enableLineActions={enableLineActions}
                                                    />
                                                    {'\n\n'}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                </>
                            )}
                        </span>
                    )
                }

                // Truncated segment
                return (
                    <span key={nestedIdx}>
                        {isNestedExpanded ? (
                            <>
                                <TextWithLinks
                                    text={nestedSeg.fullContent || ''}
                                    traceId={traceId}
                                    activeLineNumber={activeLineNumber}
                                    lineNumberPadding={lineNumberPadding}
                                    onCopyPermalink={onCopyPermalink}
                                    enableLineActions={enableLineActions}
                                />
                                <button
                                    onClick={() => toggleNestedSegment(nestedIdx)}
                                    className="text-link hover:underline cursor-pointer ml-1"
                                >
                                    [collapse]
                                </button>
                            </>
                        ) : (
                            <>
                                <button
                                    onClick={() => toggleNestedSegment(nestedIdx)}
                                    className="text-link hover:underline cursor-pointer"
                                >
                                    {nestedSeg.content}
                                </button>
                                <Tooltip
                                    title={
                                        isNestedPopoutOpen ? (
                                            <div
                                                data-popout-content
                                                className="max-h-96 overflow-auto whitespace-pre-wrap font-mono text-xs"
                                            >
                                                {nestedSeg.fullContent}
                                            </div>
                                        ) : null
                                    }
                                    containerClassName="max-w-4xl"
                                    placement="top"
                                    visible={isNestedPopoutOpen}
                                >
                                    <button
                                        data-popout-button
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            toggleNestedPopout(nestedIdx)
                                        }}
                                        className="inline-flex items-center justify-center w-4 h-4 ml-1 text-muted hover:text-default transition-colors"
                                        title="Preview truncated content"
                                    >
                                        <IconExternal className="w-3 h-3" />
                                    </button>
                                </Tooltip>
                            </>
                        )}
                    </span>
                )
            })}
        </>
    )
}
