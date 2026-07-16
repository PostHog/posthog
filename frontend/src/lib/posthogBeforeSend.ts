import posthog, { BeforeSendFn } from 'posthog-js'

// posthog-js exposes a single `before_send` config slot, so any code that wants to mutate or
// drop events before they leave the browser has to share it. Register filters through here
// instead of calling `posthog.set_config({ before_send })` directly — a direct call clobbers
// every other filter. Filters run in registration order; a filter returning `null` drops the
// event and short-circuits the rest of the chain.
const filters = new Set<BeforeSendFn>()
let installed = false

const runFilters: BeforeSendFn = (event) => {
    let current = event
    for (const filter of filters) {
        if (current === null) {
            return null
        }
        current = filter(current)
    }
    return current
}

export function registerBeforeSendFilter(filter: BeforeSendFn): () => void {
    filters.add(filter)
    if (!installed) {
        posthog.set_config({ before_send: runFilters })
        installed = true
    }
    return () => {
        filters.delete(filter)
    }
}
