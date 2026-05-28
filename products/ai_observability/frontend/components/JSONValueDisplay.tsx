import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'
import { isObject } from 'lib/utils'

import { isEmptyJSONStructure, parsePartialJSON, safeStringify } from '../utils'

function isJsonContainer(value: unknown): value is Record<string, unknown> | unknown[] {
    return Array.isArray(value) || isObject(value)
}

function parseStringifiedJsonContainer(value: unknown): unknown {
    if (typeof value !== 'string') {
        return value
    }

    const trimmed = value.trim()
    if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) {
        return value
    }

    try {
        const parsed = parsePartialJSON(value)
        const isLiteralEmptyContainer = trimmed === '{}' || trimmed === '[]'
        if (isJsonContainer(parsed) && (!isEmptyJSONStructure(parsed) || isLiteralEmptyContainer)) {
            return parsed
        }
    } catch {
        // Keep bracket-prefixed plain text, such as "[Thinking: ...]", readable.
    }

    return value
}

export function JSONValueDisplay({
    value,
    collapsed = 5,
    searchQuery,
}: {
    value: unknown
    collapsed?: number
    searchQuery?: string
}): JSX.Element {
    const parsedValue = parseStringifiedJsonContainer(value)

    if (isJsonContainer(parsedValue)) {
        return <HighlightedJSONViewer src={parsedValue} name={null} collapsed={collapsed} searchQuery={searchQuery} />
    }

    return <span className="font-mono">{safeStringify(value ?? null)}</span>
}
