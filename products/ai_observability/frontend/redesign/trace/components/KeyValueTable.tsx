import { useMemo } from 'react'

import { cn } from 'lib/utils/css-classes'

import { getJsonContainerForDisplay } from '../../../components/JSONValueDisplay'
import { toDisplayText } from './jsonText'
import { JsonTree } from './JsonTree'

export interface KeyValueTableProps {
    entries: [string, unknown][]
    className?: string
    highlightQuery?: string | null
}

function ValueCell({ value, highlightQuery }: { value: unknown; highlightQuery: string | null }): JSX.Element {
    // The viewer keeps every source it mounts, so a search must not hand it a fresh parse each time.
    const json = useMemo(() => getJsonContainerForDisplay(value, { allowEmptyContainers: false }), [value])
    return (
        <dd className="m-0 min-w-0">
            {json ? (
                <JsonTree src={json} highlightQuery={highlightQuery} />
            ) : typeof value === 'string' ? (
                <span className="whitespace-pre-wrap break-words">{value}</span>
            ) : (
                <pre className="m-0 whitespace-pre-wrap break-words text-xs">{toDisplayText(value)}</pre>
            )}
        </dd>
    )
}

export function KeyValueTable({ entries, className, highlightQuery = null }: KeyValueTableProps): JSX.Element {
    return (
        <dl className={cn('m-0 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm', className)}>
            {entries.map(([key, value]) => (
                <div key={key} className="contents">
                    <dt className="font-mono text-xs text-[var(--data-color-1)]">{key}</dt>
                    <ValueCell value={value} highlightQuery={highlightQuery} />
                </div>
            ))}
        </dl>
    )
}
