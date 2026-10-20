import type { PostHogErrorDetails } from './types.js'

export class PostHogError extends Error {
    readonly details: PostHogErrorDetails

    constructor(details: PostHogErrorDetails, options?: ErrorOptions) {
        super(details.message, options)
        this.name = 'PostHogError'
        this.details = details
    }
}
