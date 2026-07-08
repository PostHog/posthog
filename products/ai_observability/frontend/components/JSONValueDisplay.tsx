import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'
import { isObject } from 'lib/utils/guards'

import { isEmptyJSONStructure, parsePartialJSON, safeStringify } from '../utils'

export type JSONDisplayContainer = Record<string, unknown> | unknown[]

export interface JSONDisplayOptions {
    allowEmptyContainers?: boolean
}

export function isJsonContainer(value: unknown): value is JSONDisplayContainer {
    return Array.isArray(value) || isObject(value)
}

export function getJsonContainerForDisplay(value: unknown, options?: JSONDisplayOptions): JSONDisplayContainer | null {
    const allowEmptyContainers = options?.allowEmptyContainers ?? true

    if (typeof value !== 'string') {
        return isJsonContainer(value) && (allowEmptyContainers || !isEmptyJSONStructure(value)) ? value : null
    }

    const trimmed = value.trim()
    if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) {
        return null
    }

    try {
        const parsed = parsePartialJSON(value)
        const isLiteralEmptyContainer = trimmed === '{}' || trimmed === '[]'
        if (
            isJsonContainer(parsed) &&
            (!isEmptyJSONStructure(parsed) || (allowEmptyContainers && isLiteralEmptyContainer))
        ) {
            return parsed
        }
    } catch {
        // Keep bracket-prefixed plain text, such as "[Thinking: ...]", readable.
    }

    return null
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
    const parsedValue = getJsonContainerForDisplay(value)

    if (parsedValue) {
        return <HighlightedJSONViewer src={parsedValue} name={null} collapsed={collapsed} searchQuery={searchQuery} />
    }

    return <span className="font-mono">{safeStringify(value ?? null)}</span>
}
