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
 * * `person` - Person
 * `group_0` - Group 0
 * `group_1` - Group 1
 * `group_2` - Group 2
 * `group_3` - Group 3
 * `group_4` - Group 4
 */
export type CustomerProfileConfigScopeEnumApi =
    (typeof CustomerProfileConfigScopeEnumApi)[keyof typeof CustomerProfileConfigScopeEnumApi]

export const CustomerProfileConfigScopeEnumApi = {
    person: 'person',
    group_0: 'group_0',
    group_1: 'group_1',
    group_2: 'group_2',
    group_3: 'group_3',
    group_4: 'group_4',
} as const

export interface CustomerProfileConfigApi {
    readonly id: string
    scope: CustomerProfileConfigScopeEnumApi
    content?: unknown | null
    sidebar?: unknown | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedCustomerProfileConfigListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CustomerProfileConfigApi[]
}

export type CustomerProfileConfigsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
