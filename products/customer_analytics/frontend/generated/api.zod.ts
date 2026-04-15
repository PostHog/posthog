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

export const customerJourneysListResponseResultsItemNameMax = 400

export const CustomerJourneysListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            insight: zod.number(),
            name: zod.string().max(customerJourneysListResponseResultsItemNameMax),
            description: zod.string().nullish(),
            created_at: zod.iso.datetime({}),
            created_by: zod.number().nullable(),
            updated_at: zod.iso.datetime({}).nullable(),
        })
    ),
})

export const customerJourneysCreateBodyNameMax = 400

export const CustomerJourneysCreateBody = /* @__PURE__ */ zod.object({
    insight: zod.number(),
    name: zod.string().max(customerJourneysCreateBodyNameMax),
    description: zod.string().nullish(),
})

export const CustomerProfileConfigsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            scope: zod
                .enum(['person', 'group_0', 'group_1', 'group_2', 'group_3', 'group_4'])
                .describe(
                    '* `person` - Person\n* `group_0` - Group 0\n* `group_1` - Group 1\n* `group_2` - Group 2\n* `group_3` - Group 3\n* `group_4` - Group 4'
                ),
            content: zod.unknown().nullish(),
            sidebar: zod.unknown().nullish(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}).nullable(),
        })
    ),
})

export const CustomerProfileConfigsCreateBody = /* @__PURE__ */ zod.object({
    scope: zod
        .enum(['person', 'group_0', 'group_1', 'group_2', 'group_3', 'group_4'])
        .describe(
            '* `person` - Person\n* `group_0` - Group 0\n* `group_1` - Group 1\n* `group_2` - Group 2\n* `group_3` - Group 3\n* `group_4` - Group 4'
        ),
    content: zod.unknown().nullish(),
    sidebar: zod.unknown().nullish(),
})
