import { isFilledContainer, toDisplayText } from './jsonText'
import { JsonTree } from './JsonTree'
import { KeyValueTable } from './KeyValueTable'

export interface JsonValueProps {
    value: unknown
    highlightQuery?: string | null
    tableClassName?: string
    collapseStringsAfterLength?: number
}

export function JsonValue({
    value,
    highlightQuery = null,
    tableClassName,
    collapseStringsAfterLength,
}: JsonValueProps): JSX.Element {
    if (isFilledContainer(value)) {
        return Array.isArray(value) ? (
            <JsonTree
                src={value}
                highlightQuery={highlightQuery}
                collapseStringsAfterLength={collapseStringsAfterLength}
            />
        ) : (
            <KeyValueTable
                entries={Object.entries(value)}
                className={tableClassName}
                highlightQuery={highlightQuery}
                collapseStringsAfterLength={collapseStringsAfterLength}
            />
        )
    }
    if (typeof value === 'string') {
        if (collapseStringsAfterLength && value.length > collapseStringsAfterLength) {
            return (
                <details className="m-0 whitespace-pre-wrap break-words text-sm">
                    <summary className="cursor-pointer">{value.slice(0, collapseStringsAfterLength)}…</summary>
                    <span>{value.slice(collapseStringsAfterLength)}</span>
                </details>
            )
        }
        return <p className="m-0 whitespace-pre-wrap break-words text-sm">{value}</p>
    }
    return <pre className="m-0 whitespace-pre-wrap break-words text-xs">{toDisplayText(value)}</pre>
}
