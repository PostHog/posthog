import { useEffect, useState } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { findQueryAtCursor, splitQueries } from './multiQueryUtils'

export interface SaveCandidates {
    queries: string[]
    initialIndex: number
    selectionLabel: string | null
}

/**
 * Resolve which queries a save-as dialog should offer the user, given the current editor state.
 *
 * Priority:
 *   1. Non-empty editor selection → single-entry "Selection" candidate.
 *   2. Multi-statement editor → one entry per statement, initial index from cursor.
 *   3. Otherwise → the whole editor text as the only candidate.
 *
 * Kept as a pure helper so it's easy to unit test without standing up a Monaco editor.
 */
export function resolveSaveCandidates(
    queryInput: string,
    cursorOffset: number | null,
    selectionText: string | null
): SaveCandidates {
    if (selectionText) {
        const trimmed = selectionText.trim()
        if (trimmed) {
            return { queries: [trimmed], initialIndex: 0, selectionLabel: 'Selection' }
        }
    }

    const split = splitQueries(queryInput)
    if (split.length <= 1) {
        return {
            queries: [split[0]?.query ?? queryInput],
            initialIndex: 0,
            selectionLabel: null,
        }
    }

    let initialIndex = split.length - 1
    if (cursorOffset != null) {
        const match = findQueryAtCursor(split, cursorOffset)
        if (match) {
            initialIndex = split.findIndex((q) => q.start === match.start)
        }
    }

    return {
        queries: split.map((q) => q.query),
        initialIndex,
        selectionLabel: null,
    }
}

interface SaveTargetCyclerProps {
    candidates: SaveCandidates
    onChange: (query: string, index: number) => void
    children?: (query: string, index: number) => JSX.Element
}

/**
 * Pager for save-as dialogs. Shows the current target label, optional prev/next buttons when more
 * than one candidate is available, and a preview of the current query (or any custom body via the
 * `children` render prop). Calls `onChange` whenever the selection changes so callers can capture
 * the chosen query for submission.
 */
export function SaveTargetCycler({ candidates, onChange, children }: SaveTargetCyclerProps): JSX.Element | null {
    const [index, setIndex] = useState(candidates.initialIndex)

    // Clamp the active index whenever the candidate set shrinks so we never read past the end.
    useEffect(() => {
        if (candidates.queries.length > 0 && index >= candidates.queries.length) {
            setIndex(candidates.queries.length - 1)
        }
    }, [candidates.queries.length, index])

    useEffect(() => {
        const safeIndex = Math.min(index, candidates.queries.length - 1)
        if (safeIndex >= 0) {
            onChange(candidates.queries[safeIndex], safeIndex)
        }
    }, [index, candidates, onChange])

    if (candidates.queries.length === 0) {
        return null
    }

    const safeIndex = Math.min(index, candidates.queries.length - 1)
    const multi = candidates.queries.length > 1
    const label = candidates.selectionLabel ?? (multi ? `Query ${safeIndex + 1} of ${candidates.queries.length}` : null)

    if (!label && !children) {
        return null
    }

    return (
        <div className="mt-2 mb-3">
            <div className="flex items-center justify-between mb-1">
                <div className="text-muted text-xs">{label ? `Saving: ${label}` : ''}</div>
                {multi && (
                    <div className="flex items-center gap-1">
                        <LemonButton
                            size="xsmall"
                            icon={<IconChevronLeft />}
                            disabledReason={safeIndex === 0 ? 'First query' : undefined}
                            onClick={() => setIndex((i) => Math.max(0, i - 1))}
                        />
                        <LemonButton
                            size="xsmall"
                            icon={<IconChevronRight />}
                            disabledReason={safeIndex === candidates.queries.length - 1 ? 'Last query' : undefined}
                            onClick={() => setIndex((i) => Math.min(candidates.queries.length - 1, i + 1))}
                        />
                    </div>
                )}
            </div>
            {children ? (
                children(candidates.queries[safeIndex], safeIndex)
            ) : (
                <CodeSnippet language={Language.SQL} wrap compact maxLinesWithoutExpansion={8}>
                    {candidates.queries[safeIndex]}
                </CodeSnippet>
            )}
        </div>
    )
}
