import type { Rule } from '../ast/rule'

export interface Recipe {
    id: string
    rules: Rule[]
    // Fires a PostHog capture on every dispatch match — including recursive
    // delegation, so only set it on a recipe that is never delegated into (a
    // terminal catch-all like cajole), or it fires more than once per message.
    capture?: string
}
