import { useMemo } from 'react'

import { JSONViewer } from 'lib/components/JSONViewer'

import { containsQuery, JsonContainer, searchableText, toDisplayText } from './jsonText'

const OPEN_DEPTH = 2
// Captured values can nest thousands of levels deep, and React renders nested components recursively.
const SEARCH_OPEN_DEPTH = 64
// The viewer does not virtualize, so a value that opens more rows than this shows as text.
const MAX_OPEN_ROWS = 2000
// A search match turns string truncation off for the whole tree, so its text must stay small enough to lay out.
const MAX_SEARCH_OPEN_CHARS = 100_000
const ARRAY_GROUP_SIZE = 100

function openRows(value: unknown, depth: number, budget: number, groupsArrays: boolean): number {
    // A grouped array lists its groups even when it is closed.
    if (groupsArrays && Array.isArray(value) && value.length > ARRAY_GROUP_SIZE) {
        return Math.ceil(value.length / ARRAY_GROUP_SIZE)
    }
    if (depth === 0 || value === null || typeof value !== 'object') {
        return 0
    }
    let rows = 0
    for (const child of Object.values(value)) {
        rows += 1 + openRows(child, depth - 1, budget - rows, groupsArrays)
        if (rows > budget) {
            break
        }
    }
    return rows
}

export interface JsonTreeProps {
    src: JsonContainer
    highlightQuery?: string | null
}

export function JsonTree({ src, highlightQuery = null }: JsonTreeProps): JSX.Element {
    const showsQuery = useMemo(() => containsQuery(src, highlightQuery), [src, highlightQuery])
    const isTooBig = useMemo(
        () =>
            (showsQuery && searchableText(src).length > MAX_SEARCH_OPEN_CHARS) ||
            openRows(src, showsQuery ? SEARCH_OPEN_DEPTH : OPEN_DEPTH, MAX_OPEN_ROWS, !showsQuery) > MAX_OPEN_ROWS,
        [src, showsQuery]
    )
    // Array groups and cut strings ignore the open depth, so a search match opens them too.
    const searchProps = showsQuery ? { groupArraysAfterLength: 0, collapseStringsAfterLength: false as const } : {}

    // Strings wrap between words and keep line breaks. The hidden copy icon keeps its width, so values leave room for it.
    return isTooBig ? (
        <pre className="m-0 whitespace-pre-wrap break-words text-xs">{toDisplayText(src)}</pre>
    ) : (
        <div className="min-w-0 [&_.string-value]:whitespace-pre-wrap [&_.string-value]:![word-break:normal] [&_.variable-value]:max-w-[calc(100%-2rem)]">
            <JSONViewer
                key={showsQuery ? 'open' : 'collapsed'}
                src={src}
                collapsed={showsQuery ? SEARCH_OPEN_DEPTH : OPEN_DEPTH}
                escapeStrings={false}
                {...searchProps}
            />
        </div>
    )
}
