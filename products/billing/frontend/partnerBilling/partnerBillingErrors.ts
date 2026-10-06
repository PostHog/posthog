import { ApiError } from 'lib/api-error'

const UNAVAILABLE_MESSAGE = 'Billing could not answer this request. Try again in a moment.'

// The API's other refusals already end with what to do next.
const NEXT_STEP_BY_CODE: Record<string, string> = {
    not_found: 'Reload the page to see the latest billing details.',
    forbidden: 'Contact PostHog support to move it to this organization.',
    billing_rejected: 'Check your changes and try again.',
    permission_denied: 'Ask an organization admin to make this change.',
}

export function partnerBillingErrorMessage(error: unknown): string {
    if (!(error instanceof ApiError) || !error.detail) {
        return UNAVAILABLE_MESSAGE
    }
    const nextStep = error.code ? NEXT_STEP_BY_CODE[error.code] : undefined
    return nextStep ? `${error.detail} ${nextStep}` : error.detail
}

export function partnerBillingFieldError(error: unknown, field: string): string | null {
    return error instanceof ApiError && error.attr === field && error.detail ? error.detail : null
}
