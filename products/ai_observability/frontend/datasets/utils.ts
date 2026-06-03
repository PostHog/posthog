export const EMPTY_JSON = '{\n  \n}'

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
        if (typeof parsedObject !== 'object' || parsedObject === null) {
            return false
        }
    } catch {
        return false
    }
    return true
}

/**
 * Convert a JSON object to a string with pretty formatting.
 * @param json - The JSON object to convert
 * @returns The stringified JSON object or null
 */
export function prettifyJson(json?: Record<string, unknown> | null): string | null {
    let stringified = json ? JSON.stringify(json, null, 2) : null
    if (stringified === '{}') {
        stringified = EMPTY_JSON
    }
    return stringified
}
