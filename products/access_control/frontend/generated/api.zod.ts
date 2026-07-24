/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Create or update a property access control rule.
 */
export const PropertyAccessControlsCreateBody = /* @__PURE__ */ zod
    .object({
        property_definition_id: zod.string().describe('The property definition ID this rule applies to.'),
        access_level: zod
            .enum(['read_write', 'read', 'none'])
            .describe('\* `read_write` - read_write\n\* `read` - read\n\* `none` - none')
            .describe(
                'The access level to set for this rule.\n\n\* `read_write` - read_write\n\* `read` - read\n\* `none` - none'
            ),
        organization_member: zod.uuid().nullish().describe('The organization member UUID to set an override for.'),
        role: zod.uuid().nullish().describe('The role UUID to set an override for.'),
    })
    .describe('Request body for upserting a rule (create or update).')
