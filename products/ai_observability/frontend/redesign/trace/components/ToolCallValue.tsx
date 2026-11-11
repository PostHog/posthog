import { useLayoutEffect, useMemo, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'

import { isPlainObject, searchableText, toDisplayText } from './jsonText'
import { KeyValueTable } from './KeyValueTable'

// A value longer than this folds to one line, so a message with several tool calls still shows every call.
const FOLDED_LINES = 8
const FOLDED_CHARS = 640

export interface ToolCallValueProps {
    value: unknown
    highlightQuery?: string | null
}

function isLong(text: string): boolean {
    return text.length > FOLDED_CHARS || text.split('\n').length > FOLDED_LINES
}

function ValueBody({ value }: { value: unknown }): JSX.Element {
    return isPlainObject(value) && Object.keys(value).length > 0 ? (
        <KeyValueTable entries={Object.entries(value)} className="gap-x-4 gap-y-1 font-mono text-xs" />
    ) : (
        <pre className="m-0 whitespace-pre-wrap break-words text-xs">{toDisplayText(value)}</pre>
    )
}

function FoldedValue({ value, highlightQuery }: Required<ToolCallValueProps>): JSX.Element {
    const [details, setDetails] = useState<HTMLDetailsElement | null>(null)
    const [isOpen, setIsOpen] = useState(false)
    // A closed fold holds only the escaped one-line preview, so the decoded value decides whether the query is in it.
    const showsQuery = useMemo(
        () => !!highlightQuery && searchableText(value).toLowerCase().includes(highlightQuery.toLowerCase()),
        [value, highlightQuery]
    )
    useLayoutEffect(() => {
        if (details && showsQuery) {
            details.open = true
        }
    }, [details, showsQuery])

    // Only one of the line and the body is in the page at a time. A closed fold then costs one text node however big
    // the value is, and the search highlighter never marks text that is not shown.
    return (
        <details
            ref={setDetails}
            onToggle={(event) => setIsOpen(event.currentTarget.open)}
            className="group min-w-0 px-2 py-1"
        >
            <summary
                className="flex cursor-pointer list-none items-center gap-1 [&::-webkit-details-marker]:hidden"
                data-attr="trace-view-tool-value-toggle"
            >
                <IconChevronRight className="shrink-0 text-secondary transition-transform group-open:rotate-90 motion-reduce:transition-none" />
                {isOpen ? null : (
                    <span className="min-w-0 truncate font-mono text-xs">
                        {typeof value === 'string' ? value : JSON.stringify(value)}
                    </span>
                )}
            </summary>
            {isOpen ? <ValueBody value={value} /> : null}
        </details>
    )
}

export function ToolCallValue({ value, highlightQuery = null }: ToolCallValueProps): JSX.Element {
    if (isLong(toDisplayText(value))) {
        return <FoldedValue value={value} highlightQuery={highlightQuery} />
    }
    return (
        <div className="min-w-0 px-2 py-1">
            <ValueBody value={value} />
        </div>
    )
}
