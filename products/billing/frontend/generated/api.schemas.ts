/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface BillingApi {
    /** @maxLength 100 */
    plan: string
    billing_limit: number
}

export interface PaginatedBillingListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: BillingApi[]
}

export interface PatchedBillingApi {
    /** @maxLength 100 */
    plan?: string
    billing_limit?: number
}

export type BillingListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
