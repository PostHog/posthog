import posthog from 'posthog-js'

export interface InitialReferrerSignupFields {
    initial_referring_domain?: string
    initial_utm_source?: string
}

function nonEmptyString(value: unknown): string | undefined {
    return typeof value === 'string' && value ? value : undefined
}

/**
 * Where this browser came from on its first visit, as posthog-js stored it. The signup request
 * carries it so the server can tell when an AI assistant referred the new organization.
 */
export function initialReferrerSignupFields(): InitialReferrerSignupFields {
    const initialProps = posthog.persistence?.get_initial_props() ?? {}

    const fields: InitialReferrerSignupFields = {}
    const referringDomain = nonEmptyString(initialProps['$initial_referring_domain'])
    if (referringDomain) {
        fields.initial_referring_domain = referringDomain
    }
    const utmSource = nonEmptyString(initialProps['$initial_utm_source'])
    if (utmSource) {
        fields.initial_utm_source = utmSource
    }

    return fields
}
