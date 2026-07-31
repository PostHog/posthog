/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const AccessLevelEnumApi = zod
    .enum(['read_write', 'read', 'none'])
    .describe('\* `read_write` - read_write\n\* `read` - read\n\* `none` - none')

export type AccessLevelEnumApi = zod.input<typeof AccessLevelEnumApi>
export type AccessLevelEnumApiOutput = zod.output<typeof AccessLevelEnumApi>

export const PropertyAccessControlRuleApi = zod
    .object({
        id: zod.uuid(),
        access_level: AccessLevelEnumApi.describe(
            'The access level for this rule.\n\n\* `read_write` - read_write\n\* `read` - read\n\* `none` - none'
        ),
        organization_member: zod
            .uuid()
            .nullable()
            .describe('The organization member UUID this rule applies to, if any.'),
        role: zod.uuid().nullable().describe('The role UUID this rule applies to, if any.'),
        created_by: zod.number().nullable(),
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
    })
    .describe('Serializes a single access control rule DTO.')

export type PropertyAccessControlRuleApi = zod.input<typeof PropertyAccessControlRuleApi>
export type PropertyAccessControlRuleApiOutput = zod.output<typeof PropertyAccessControlRuleApi>

export const PropertyAccessControlStateApi = zod
    .object({
        access_controls: zod
            .array(PropertyAccessControlRuleApi)
            .describe('List of all access control rules for this property definition.'),
        available_access_levels: zod.array(zod.string()).describe('Available access levels that can be assigned.'),
        default_access_level: zod.string().describe('The default access level when no rules match.'),
    })
    .describe(
        'Serializes the aggregate state for a property definition.\n\nPreserves the existing API shape: ``access_controls`` is the list\nof rules, plus the available levels and the computed default.'
    )

export type PropertyAccessControlStateApi = zod.input<typeof PropertyAccessControlStateApi>
export type PropertyAccessControlStateApiOutput = zod.output<typeof PropertyAccessControlStateApi>

export const PropertyAccessControlUpdateApi = zod
    .object({
        property_definition_id: zod.string().describe('The property definition ID this rule applies to.'),
        access_level: AccessLevelEnumApi.describe(
            'The access level to set for this rule.\n\n\* `read_write` - read_write\n\* `read` - read\n\* `none` - none'
        ),
        organization_member: zod.uuid().nullish().describe('The organization member UUID to set an override for.'),
        role: zod.uuid().nullish().describe('The role UUID to set an override for.'),
    })
    .describe('Request body for upserting a rule (create or update).')

export type PropertyAccessControlUpdateApi = zod.input<typeof PropertyAccessControlUpdateApi>
export type PropertyAccessControlUpdateApiOutput = zod.output<typeof PropertyAccessControlUpdateApi>
