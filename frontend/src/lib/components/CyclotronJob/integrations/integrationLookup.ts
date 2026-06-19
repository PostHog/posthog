import { IntegrationType } from '~/types'

export type IntegrationIdValue = IntegrationType['id'] | string | null | undefined

/**
 * Whether a stored form value points to a given integration.
 *
 * `integration.id` is a JSON number from the API, but `value` can arrive as a
 * string when the form is hydrated from a source's stored `job_inputs` (Postgres
 * JSONB preserves whatever was originally written, and some source flows end up
 * persisting the OAuth integration ID as a string). Strict equality on a number
 * vs a string silently misses — `7 === "7"` is `false` in JS — which would
 * otherwise trip the "previously selected ... is no longer available" banner
 * and de-highlight the currently-selected menu item in `IntegrationChoice` for
 * every loaded source. Coercing both sides to Number fixes the comparison
 * without changing behavior for code paths that already pass numbers.
 *
 * Empty/blank values never match — callers should treat them as "no selection"
 * rather than "selection matching nothing".
 */
export function matchesIntegrationIdValue(integrationId: IntegrationType['id'], value: IntegrationIdValue): boolean {
    if (value === undefined || value === null || value === '') {
        return false
    }
    const target = Number(value)
    if (!Number.isFinite(target)) {
        return false
    }
    return Number(integrationId) === target
}

/**
 * Lookup helper built on top of `matchesIntegrationIdValue`. Returns the
 * integration matching the form value, or `undefined` if the list isn't loaded
 * or the value doesn't correspond to any integration.
 */
export function findIntegrationByFormValue(
    integrations: IntegrationType[] | null | undefined,
    value: IntegrationIdValue
): IntegrationType | undefined {
    if (!integrations) {
        return undefined
    }
    return integrations.find((integration) => matchesIntegrationIdValue(integration.id, value))
}
