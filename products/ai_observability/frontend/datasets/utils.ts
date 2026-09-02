export const EMPTY_JSON = '{\n  \n}'

export type JSONValue = Record<string, unknown> | unknown[] | string | number | boolean | null

function isJsonObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

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
        const parsedObject: unknown = JSON.parse(maybeJson)
        if (isJsonObject(parsedObject) && Object.keys(parsedObject).length > 0) {
            return parsedObject
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
        return isJsonObject(JSON.parse(maybeJson))
    } catch {
        return false
    }
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
    const parsedObject: unknown = maybeJson ? JSON.parse(maybeJson) : {}
    if (!isJsonObject(parsedObject)) {
        throw new TypeError('Expected a JSON object')
    }
    return parsedObject
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
