import { isFilledContainer, toDisplayText } from './jsonText'
import { JsonTree } from './JsonTree'
import { KeyValueTable } from './KeyValueTable'

export interface JsonValueProps {
    value: unknown
    highlightQuery?: string | null
    tableClassName?: string
}

export function JsonValue({ value, highlightQuery = null, tableClassName }: JsonValueProps): JSX.Element {
    if (isFilledContainer(value)) {
        return Array.isArray(value) ? (
            <JsonTree src={value} highlightQuery={highlightQuery} />
        ) : (
            <KeyValueTable entries={Object.entries(value)} className={tableClassName} highlightQuery={highlightQuery} />
        )
    }
    if (typeof value === 'string') {
        return <p className="m-0 whitespace-pre-wrap break-words text-sm">{value}</p>
    }
    return <pre className="m-0 whitespace-pre-wrap break-words text-xs">{toDisplayText(value)}</pre>
}
