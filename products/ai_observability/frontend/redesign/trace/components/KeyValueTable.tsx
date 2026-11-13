import { cn } from 'lib/utils/css-classes'

import { getJsonContainerForDisplay } from '../../../components/JSONValueDisplay'
import { toDisplayText } from './jsonText'
import { JsonTree } from './JsonTree'

export interface KeyValueTableProps {
    entries: [string, unknown][]
    className?: string
    highlightQuery?: string | null
}

export function KeyValueTable({ entries, className, highlightQuery = null }: KeyValueTableProps): JSX.Element {
    return (
        <dl className={cn('m-0 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm', className)}>
            {entries.map(([key, value]) => {
                const json = getJsonContainerForDisplay(value, { allowEmptyContainers: false })
                return (
                    <div key={key} className="contents">
                        <dt className="font-mono text-xs text-[var(--data-color-1)]">{key}</dt>
                        <dd className="m-0 min-w-0">
                            {json ? (
                                <JsonTree src={json} highlightQuery={highlightQuery} />
                            ) : typeof value === 'string' ? (
                                <span className="whitespace-pre-wrap break-words">{value}</span>
                            ) : (
                                <pre className="m-0 whitespace-pre-wrap break-words text-xs">
                                    {toDisplayText(value)}
                                </pre>
                            )}
                        </dd>
                    </div>
                )
            })}
        </dl>
    )
}
