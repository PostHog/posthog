import { JsonString } from './JsonString'
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
        return <JsonString value={value} collapseStringsAfterLength={collapseStringsAfterLength} />
    }
    return <pre className="m-0 whitespace-pre-wrap break-words text-xs">{toDisplayText(value)}</pre>
}
