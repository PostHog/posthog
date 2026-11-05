import { useLayoutEffect, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'

import { isPlainObject, toDisplayText } from './jsonText'
import { KeyValueTable } from './KeyValueTable'
import { useShowsQuery } from './useShowsQuery'

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
    const showsQuery = useShowsQuery(details, highlightQuery)
    useLayoutEffect(() => {
        if (details && showsQuery) {
            details.open = true
        }
    }, [details, showsQuery])

    return (
        <details ref={setDetails} className="group min-w-0 px-2 py-1">
            <summary
                className="flex cursor-pointer list-none items-center gap-1 [&::-webkit-details-marker]:hidden"
                data-attr="trace-view-tool-value-toggle"
            >
                <IconChevronRight className="shrink-0 text-secondary transition-transform group-open:rotate-90 motion-reduce:transition-none" />
                <span className="min-w-0 truncate font-mono text-xs group-open:hidden">
                    {typeof value === 'string' ? value : JSON.stringify(value)}
                </span>
            </summary>
            <ValueBody value={value} />
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
