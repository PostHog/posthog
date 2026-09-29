import { toDisplayText } from './jsonText'

export interface KeyValueTableProps {
    entries: [string, unknown][]
}

export function KeyValueTable({ entries }: KeyValueTableProps): JSX.Element {
    return (
        <dl className="m-0 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
            {entries.map(([key, value]) => (
                <div key={key} className="contents">
                    <dt className="font-mono text-xs text-[var(--data-color-1)]">{key}</dt>
                    <dd className="m-0 min-w-0">
                        {typeof value === 'string' ? (
                            <span className="whitespace-pre-wrap break-words">{value}</span>
                        ) : (
                            <pre className="m-0 overflow-auto text-xs">{toDisplayText(value)}</pre>
                        )}
                    </dd>
                </div>
            ))}
        </dl>
    )
}
