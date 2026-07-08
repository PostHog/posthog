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
 * * `read_write` - read_write
 * * `read` - read
 * * `none` - none
 */
export type AccessLevelEnumApi = (typeof AccessLevelEnumApi)[keyof typeof AccessLevelEnumApi]

export const AccessLevelEnumApi = {
    ReadWrite: 'read_write',
    Read: 'read',
    None: 'none',
} as const

/**
 * Serializes a single access control rule DTO.
 */
export interface PropertyAccessControlRuleApi {
    readonly id: string
    /** The access level for this rule.
     *
     * * `read_write` - read_write
     * * `read` - read
     * * `none` - none */
    access_level: AccessLevelEnumApi
    /**
     * The organization member UUID this rule applies to, if any.
     * @nullable
     */
    organization_member: string | null
    /**
     * The role UUID this rule applies to, if any.
     * @nullable
     */
    role: string | null
    /** @nullable */
    readonly created_by: number | null
    readonly created_at: string
    readonly updated_at: string
}

/**
 * Serializes the aggregate state for a property definition.
 *
 * Preserves the existing API shape: ``access_controls`` is the list
 * of rules, plus the available levels and the computed default.
 */
export interface PropertyAccessControlStateApi {
    /** List of all access control rules for this property definition. */
    access_controls: PropertyAccessControlRuleApi[]
    /** Available access levels that can be assigned. */
    available_access_levels: string[]
    /** The default access level when no rules match. */
    default_access_level: string
}

/**
 * Request body for upserting a rule (create or update).
 */
export interface PropertyAccessControlUpdateApi {
    /** The property definition ID this rule applies to. */
    property_definition_id: string
    /** The access level to set for this rule.
     *
     * * `read_write` - read_write
     * * `read` - read
     * * `none` - none */
    access_level: AccessLevelEnumApi
    /**
     * The organization member UUID to set an override for.
     * @nullable
     */
    organization_member?: string | null
    /**
     * The role UUID to set an override for.
     * @nullable
     */
    role?: string | null
}

export type PropertyAccessControlsRetrieveParams = {
    /**
     * The property definition ID to fetch access control rules for.
     */
    property_definition_id: string
}

export type PropertyAccessControlsDestroyParams = {
    /**
     * The organization member UUID whose override should be deleted.
     */
    organization_member?: string
    /**
     * The property definition ID the rule applies to.
     */
    property_definition_id: string
    /**
     * The role UUID whose override should be deleted.
     */
    role?: string
}
