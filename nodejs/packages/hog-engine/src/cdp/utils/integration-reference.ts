/**
 * The string form of a reference to one integration. It matches `IntegrationReference` in
 * `posthog/integrations/references.py`: a legacy row id is its decimal string ("123"), and a row
 * in the credentials service has a lowercase hyphenated UUID.
 */
export type IntegrationReference = string

/** Hog function inputs store a legacy id as a number, so callers can give either form. */
export type IntegrationIdInput = number | string

const LEGACY_ID_PATTERN = /^(0|[1-9][0-9]*)$/
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

/**
 * Returns the canonical reference, or null if the value is not one. Like the Python parser, only
 * canonical strings are accepted ("05" and an uppercase UUID are rejected), so each row has one
 * form and one cache key.
 */
export function toIntegrationReference(value: unknown): IntegrationReference | null {
    if (typeof value === 'number') {
        return Number.isSafeInteger(value) && value >= 0 ? String(value) : null
    }
    if (typeof value === 'string' && (LEGACY_ID_PATTERN.test(value) || UUID_PATTERN.test(value))) {
        return value
    }
    return null
}

/** Returns the legacy row id of a reference, or null for a UUID reference. */
export function legacyIdOfReference(reference: IntegrationReference): number | null {
    if (!LEGACY_ID_PATTERN.test(reference)) {
        return null
    }
    const legacyId = Number(reference)
    return Number.isSafeInteger(legacyId) ? legacyId : null
}
