// The billing service rejects a breakdown that is too large to return interactively.
// It responds with this code and a detail string that tells the user how to narrow the query.
// Both the usage tab and the spend tab share this error.
export const BILLING_USAGE_QUERY_TOO_LARGE_CODE = 'usage_breakdown_too_large'

export interface BillingUsageError {
    code: string
    detail: string
}

export const getBillingUsageError = (error: unknown): BillingUsageError | null => {
    if (!error || typeof error !== 'object') {
        return null
    }

    const candidate = error as { code?: unknown; detail?: unknown }
    return typeof candidate.code === 'string' && typeof candidate.detail === 'string'
        ? { code: candidate.code, detail: candidate.detail }
        : null
}
