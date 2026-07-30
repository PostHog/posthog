export const EMPTY_JSON = '{\n  \n}'

export type JSONValue = Record<string, unknown> | unknown[] | string | number | boolean | null

/**
 * Coerce a string to a valid JSON object or null.
 * @param maybeJson - The string to coerce
 * @returns The coerced JSON object or null
 */
export function coerceJsonToObject(maybeJson: string | null): Record<string, unknown> | null {
    if (!maybeJson) {
        return null
    }
    try {
        const parsedObject = JSON.parse(maybeJson)
        // Regular object or null
        if (typeof parsedObject === 'object' && Object.keys(parsedObject).length > 0) {
            return parsedObject as Record<string, unknown>
        }
        return null
    } catch {
        return null
    }
}

/**
 * Check if the metadata is a valid JSON object or is an empty string.
 * @param metadata - The metadata to check
 * @returns True if the metadata is valid, false otherwise
 */
export function isStringJsonObject(maybeJson: string | null): boolean {
    if (!maybeJson) {
        return true
    }
    try {
        const parsedObject = JSON.parse(maybeJson)
        if (typeof parsedObject !== 'object' || parsedObject === null || Array.isArray(parsedObject)) {
            return false
        }
    } catch {
        return false
    }
    return true
}

export function isStringJsonValue(maybeJson: string | null, allowNull: boolean = true): boolean {
    if (!maybeJson) {
        return allowNull
    }
    try {
        const parsedValue = JSON.parse(maybeJson)
        return allowNull || parsedValue !== null
    } catch {
        return false
    }
}

export function parseJsonValue(maybeJson: string | null): JSONValue {
    return maybeJson ? (JSON.parse(maybeJson) as JSONValue) : null
}

export function parseJsonObject(maybeJson: string | null): Record<string, unknown> {
    return (maybeJson ? JSON.parse(maybeJson) : {}) as Record<string, unknown>
}

export function normalizeJsonValue(value: unknown, fallback: JSONValue): JSONValue {
    try {
        const serializedValue = JSON.stringify(value)
        return serializedValue === undefined ? fallback : (JSON.parse(serializedValue) as JSONValue)
    } catch {
        return fallback
    }
}

/**
 * Convert a JSON object to a string with pretty formatting.
 * @param json - The JSON object to convert
 * @returns The stringified JSON object or null
 */
export function prettifyJson(json?: unknown): string | null {
    if (json === undefined || json === null) {
        return null
    }

    let stringified = JSON.stringify(json, null, 2)
    if (stringified === '{}') {
        stringified = EMPTY_JSON
    }
    return stringified ?? null
}
