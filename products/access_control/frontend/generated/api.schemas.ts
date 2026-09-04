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
 * A stored rule on one object, as configured for a subject.
 */
export interface AccessControlObjectRuleApi {
    /** The object's resource type, for example `dashboard`. */
    resource: string
    /** The object's primary key. */
    resource_id: string
    /** The object's display name. Falls back to the id when it has no name. */
    name: string
    /**
     * The object's short id, for models that link by one (insights, notebooks).
     * @nullable
     */
    short_id: string | null
    /** The level the rule grants or restricts to. */
    access_level: string
}

export interface AccessControlObjectRulesResponseApi {
    /** The subject's object rules, sorted by resource and name. */
    results: AccessControlObjectRuleApi[]
}

/**
 * A stored rule on one property definition, as configured for a subject.
 */
export interface AccessControlPropertyRuleApi {
    /** The property definition id. */
    property_definition_id: string
    /** The property name. */
    property: string
    /** Whether the property is a `person` or an `event` property. */
    property_type: string
    /** The rule's level: `none`, `read` or `read_write`. */
    access_level: string
}

export interface AccessControlPropertyRulesResponseApi {
    /** The subject's property rules, sorted by property type and name. */
    results: AccessControlPropertyRuleApi[]
}

export interface AccessControlResourceDefaultApi {
    /**
     * The stored default level for this resource type. Null when the built-in default applies.
     * @nullable
     */
    access_level: string | null
    /** The lowest level this resource type allows. */
    minimum: string
    /** The highest level this resource type allows. */
    maximum: string
}

/**
 * The default level per resource type, keyed by resource name.
 */
export type AccessControlDefaultsResponseApiResourceAccessLevels = { [key: string]: AccessControlResourceDefaultApi }

export interface AccessControlObjectRuleResourceApi {
    /** A resource type that supports rules on single objects. */
    resource: string
    /** The levels an object rule on this resource type accepts, lowest first. */
    available_access_levels: string[]
    /** The lowest level an object rule on this resource can set. */
    minimum_access_level: string
}

/**
 * The project's defaults: what everyone without a rule of their own gets.
 */
export interface AccessControlDefaultsResponseApi {
    /** The project access levels, lowest first. */
    available_project_levels: string[]
    /** The resource access levels, lowest first. */
    available_resource_levels: string[]
    /** Whether the caller may change access rules in this project. */
    can_edit: boolean
    /** The default project access level for members. */
    project_access_level: string
    /** The default level per resource type, keyed by resource name. */
    resource_access_levels: AccessControlDefaultsResponseApiResourceAccessLevels
    /** The resource types that accept rules on single objects, with the levels each accepts. */
    object_rule_resources: AccessControlObjectRuleResourceApi[]
}

export interface AccessControlMemberUserApi {
    /** The user's UUID. */
    uuid: string
    /** The user's first name. */
    first_name: string
    /** The user's last name. */
    last_name: string
    /** The user's email. */
    email: string
}

/**
 * * `1` - member
 * * `8` - administrator
 * * `15` - owner
 */
export type OrganizationMembershipLevelEnumApi =
    (typeof OrganizationMembershipLevelEnumApi)[keyof typeof OrganizationMembershipLevelEnumApi]

export const OrganizationMembershipLevelEnumApi = {
    Number1: 1,
    Number8: 8,
    Number15: 15,
} as const

/**
 * * `object` - object
 * * `parent_object` - parent_object
 * * `resource` - resource
 * * `parent_resource` - parent_resource
 * * `system_default` - system_default
 * * `org_admin` - org_admin
 * * `creator` - creator
 * * `org_membership` - org_membership
 */
export type ResolvedAccessSourceEnumApi = (typeof ResolvedAccessSourceEnumApi)[keyof typeof ResolvedAccessSourceEnumApi]

export const ResolvedAccessSourceEnumApi = {
    Object: 'object',
    ParentObject: 'parent_object',
    Resource: 'resource',
    ParentResource: 'parent_resource',
    SystemDefault: 'system_default',
    OrgAdmin: 'org_admin',
    Creator: 'creator',
    OrgMembership: 'org_membership',
} as const

/**
 * * `member` - member
 * * `role` - role
 * * `default` - default
 */
export type ResolvedAccessSourceSubjectEnumApi =
    (typeof ResolvedAccessSourceSubjectEnumApi)[keyof typeof ResolvedAccessSourceSubjectEnumApi]

export const ResolvedAccessSourceSubjectEnumApi = {
    Member: 'member',
    Role: 'role',
    Default: 'default',
} as const

/**
 * A resolved access level with the rule that supplied it — the wire form of `ResolvedAccess`.
 */
export interface ResolvedAccessApi {
    /** The access level that applies. */
    access_level: string
    /** How the level was derived: a rule on the object, its parent object, the resource, the parent resource, the built-in default, or one of the bypasses (org admin, creator, organization membership).
     *
     * * `object` - object
     * * `parent_object` - parent_object
     * * `resource` - resource
     * * `parent_resource` - parent_resource
     * * `system_default` - system_default
     * * `org_admin` - org_admin
     * * `creator` - creator
     * * `org_membership` - org_membership */
    source: ResolvedAccessSourceEnumApi
    /** Whose rule decided: a member's own, a role's, or the default for everyone. Null when no rule did.
     *
     * * `member` - member
     * * `role` - role
     * * `default` - default */
    source_subject: ResolvedAccessSourceSubjectEnumApi | null
    /** The resource the deciding rule belongs to. */
    source_resource: string
    /**
     * The deciding rule's object id, when it is an object-level rule (e.g. the source a table inherits from).
     * @nullable
     */
    source_resource_id: string | null
}

/**
 * One subject's access to one scope (the project, or a whole resource type): what is stored,
 * what is enforced, and where the enforced level comes from.
 */
export interface SubjectAccessEntryApi {
    /**
     * The subject's own stored rule for this scope. Null when the subject has no rule of its own here.
     * @nullable
     */
    access_level: string | null
    /**
     * The level that is enforced for the subject after defaults, roles and bypasses are resolved. Null when nothing resolves, for example a resource the organization is not entitled to.
     * @nullable
     */
    effective_access_level: string | null
    /** The level the subject falls back to without a rule of its own, with the rule that supplies it. Read `source` and `source_subject` to tell a role rule from the project default or an org-admin bypass. */
    inherited_access: ResolvedAccessApi | null
    /** The lowest level this scope allows. */
    minimum: string
    /** The highest level this scope allows. */
    maximum: string
}

/**
 * Access per resource type, keyed by resource name (for example `dashboard`, `feature_flag`).
 */
export type AccessControlMemberAccessApiResources = { [key: string]: SubjectAccessEntryApi }

/**
 * A member's resolved access to the project and to every resource type in it.
 */
export interface AccessControlMemberAccessApi {
    /** The organization membership id. Use it as `member_id` on the member rule endpoints. */
    organization_membership_id: string
    /** The member's identity. */
    user: AccessControlMemberUserApi
    /** The member's organization level: 1 member, 8 admin, 15 owner. Admins and owners bypass every rule.
     *
     * * `1` - member
     * * `8` - administrator
     * * `15` - owner */
    organization_level: OrganizationMembershipLevelEnumApi
    /** Access to the project itself. */
    project: SubjectAccessEntryApi
    /** Access per resource type, keyed by resource name (for example `dashboard`, `feature_flag`). */
    resources: AccessControlMemberAccessApiResources
}

export interface AccessControlMembersResponseApi {
    /** The project access levels, lowest first. */
    available_project_levels: string[]
    /** The resource access levels, lowest first. */
    available_resource_levels: string[]
    /** Whether the caller may change access rules in this project. */
    can_edit: boolean
    /** One entry per organization member. */
    results: AccessControlMemberAccessApi[]
}

/**
 * Access per resource type, keyed by resource name (for example `dashboard`, `feature_flag`).
 */
export type AccessControlRoleAccessApiResources = { [key: string]: SubjectAccessEntryApi }

/**
 * A role's resolved access to the project and to every resource type in it.
 */
export interface AccessControlRoleAccessApi {
    /** The role id. Use it as `role_id` on the role rule endpoints. */
    role_id: string
    /** The role's name. */
    role_name: string
    /** Access to the project itself. */
    project: SubjectAccessEntryApi
    /** Access per resource type, keyed by resource name (for example `dashboard`, `feature_flag`). */
    resources: AccessControlRoleAccessApiResources
}

export interface AccessControlRolesResponseApi {
    /** The project access levels, lowest first. */
    available_project_levels: string[]
    /** The resource access levels, lowest first. */
    available_resource_levels: string[]
    /** Whether the caller may change access rules in this project. */
    can_edit: boolean
    /** One entry per role in the organization. */
    results: AccessControlRoleAccessApi[]
}

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

export type OrganizationsProjectsAccessControlMemberObjectsRetrieveParams = {
    /**
     * The organization membership id, as `organization_membership_id` in the members endpoint.
     */
    member_id: string
}

export type OrganizationsProjectsAccessControlMemberPropertiesRetrieveParams = {
    /**
     * The organization membership id, as `organization_membership_id` in the members endpoint.
     */
    member_id: string
}

export type OrganizationsProjectsAccessControlMembersRetrieveParams = {
    /**
     * Narrow the list to one organization membership id.
     */
    member_id?: string
}

export type OrganizationsProjectsAccessControlRoleObjectsRetrieveParams = {
    /**
     * The role id, as `role_id` in the roles endpoint.
     */
    role_id: string
}

export type OrganizationsProjectsAccessControlRolePropertiesRetrieveParams = {
    /**
     * The role id, as `role_id` in the roles endpoint.
     */
    role_id: string
}

export type OrganizationsProjectsAccessControlRolesRetrieveParams = {
    /**
     * Narrow the list to one role.
     */
    role_id?: string
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
