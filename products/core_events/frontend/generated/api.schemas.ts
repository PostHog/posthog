/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `acquisition` - Acquisition
 * `activation` - Activation
 * `monetization` - Monetization
 * `expansion` - Expansion
 * `referral` - Referral
 * `retention` - Retention
 * `churn` - Churn
 * `reactivation` - Reactivation
 */
export type CategoryEnumApi = (typeof CategoryEnumApi)[keyof typeof CategoryEnumApi]

export const CategoryEnumApi = {
    acquisition: 'acquisition',
    activation: 'activation',
    monetization: 'monetization',
    expansion: 'expansion',
    referral: 'referral',
    retention: 'retention',
    churn: 'churn',
    reactivation: 'reactivation',
} as const

export interface CoreEventApi {
    readonly id: string
    /**
     * Display name for this core event
     * @maxLength 255
     */
    name: string
    /** Optional description */
    description?: string
    /** Lifecycle category for this core event

* `acquisition` - Acquisition
* `activation` - Activation
* `monetization` - Monetization
* `expansion` - Expansion
* `referral` - Referral
* `retention` - Retention
* `churn` - Churn
* `reactivation` - Reactivation */
    category: CategoryEnumApi
    /** Filter configuration - event, action, or data warehouse node */
    filter: unknown
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedCoreEventListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CoreEventApi[]
}

export interface PatchedCoreEventApi {
    readonly id?: string
    /**
     * Display name for this core event
     * @maxLength 255
     */
    name?: string
    /** Optional description */
    description?: string
    /** Lifecycle category for this core event

* `acquisition` - Acquisition
* `activation` - Activation
* `monetization` - Monetization
* `expansion` - Expansion
* `referral` - Referral
* `retention` - Retention
* `churn` - Churn
* `reactivation` - Reactivation */
    category?: CategoryEnumApi
    /** Filter configuration - event, action, or data warehouse node */
    filter?: unknown
    readonly created_at?: string
    readonly updated_at?: string
}

export type CoreEventsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
