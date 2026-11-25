import { cn } from 'lib/utils/css-classes'

import { JsonString } from './JsonString'
import { isFilledContainer, toDisplayText } from './jsonText'
import { JsonTree } from './JsonTree'

export interface KeyValueTableProps {
    entries: [string, unknown][]
    className?: string
    highlightQuery?: string | null
    collapseStringsAfterLength?: number
}

export function KeyValueTable({
    entries,
    className,
    highlightQuery = null,
    collapseStringsAfterLength,
}: KeyValueTableProps): JSX.Element {
    return (
        <dl className={cn('m-0 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm', className)}>
            {entries.map(([key, value]) => (
                <div key={key} className="contents">
                    <dt className="font-mono text-xs text-[var(--data-color-1)]">{key}</dt>
                    <dd className="m-0 min-w-0">
                        {isFilledContainer(value) ? (
                            <JsonTree
                                src={value}
                                highlightQuery={highlightQuery}
                                collapseStringsAfterLength={collapseStringsAfterLength}
                            />
                        ) : typeof value === 'string' ? (
                            <JsonString value={value} collapseStringsAfterLength={collapseStringsAfterLength} />
                        ) : (
                            <pre className="m-0 whitespace-pre-wrap break-words text-xs">{toDisplayText(value)}</pre>
                        )}
                    </dd>
                </div>
            ))}
        </dl>
    )
}
