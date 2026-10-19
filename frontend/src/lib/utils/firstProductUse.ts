import posthog from 'posthog-js'

const setThisPageLoad = new Set<string>()

/**
 * Records when a person first used a product as a `$set_once` person property (e.g. `first_used_logs_at`).
 * Surveys target on it to wait until someone has used a product for a while before asking for feedback.
 */
export function setFirstProductUse(property: string): void {
    if (setThisPageLoad.has(property)) {
        return
    }
    setThisPageLoad.add(property)
    posthog.setPersonProperties(undefined, { [property]: new Date().toISOString() })
}
