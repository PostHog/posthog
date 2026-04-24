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

export const customerJourneysCreateBodyNameMax = 400

export const CustomerJourneysCreateBody = /* @__PURE__ */ zod.object({
    insight: zod.number(),
    name: zod.string().max(customerJourneysCreateBodyNameMax),
    description: zod.string().nullish(),
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

export const groupsTypesMetricsCreateBodyNameMax = 255

export const groupsTypesMetricsCreateBodyIntervalMin = -2147483648
export const groupsTypesMetricsCreateBodyIntervalMax = 2147483647

export const groupsTypesMetricsCreateBodyMathPropertyMax = 255

export const GroupsTypesMetricsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(groupsTypesMetricsCreateBodyNameMax),
    format: zod.enum(['numeric', 'currency']).optional().describe('* `numeric` - numeric\n* `currency` - currency'),
    interval: zod
        .number()
        .min(groupsTypesMetricsCreateBodyIntervalMin)
        .max(groupsTypesMetricsCreateBodyIntervalMax)
        .optional()
        .describe('In days'),
    display: zod.enum(['number', 'sparkline']).optional().describe('* `number` - number\n* `sparkline` - sparkline'),
    filters: zod.unknown(),
    math: zod.enum(['count', 'sum']).optional().describe('* `count` - count\n* `sum` - sum'),
    math_property: zod.string().max(groupsTypesMetricsCreateBodyMathPropertyMax).nullish(),
})

export const groupsTypesMetricsUpdateBodyNameMax = 255

export const groupsTypesMetricsUpdateBodyIntervalMin = -2147483648
export const groupsTypesMetricsUpdateBodyIntervalMax = 2147483647

export const groupsTypesMetricsUpdateBodyMathPropertyMax = 255

export const GroupsTypesMetricsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(groupsTypesMetricsUpdateBodyNameMax),
    format: zod.enum(['numeric', 'currency']).optional().describe('* `numeric` - numeric\n* `currency` - currency'),
    interval: zod
        .number()
        .min(groupsTypesMetricsUpdateBodyIntervalMin)
        .max(groupsTypesMetricsUpdateBodyIntervalMax)
        .optional()
        .describe('In days'),
    display: zod.enum(['number', 'sparkline']).optional().describe('* `number` - number\n* `sparkline` - sparkline'),
    filters: zod.unknown(),
    math: zod.enum(['count', 'sum']).optional().describe('* `count` - count\n* `sum` - sum'),
    math_property: zod.string().max(groupsTypesMetricsUpdateBodyMathPropertyMax).nullish(),
})

export const groupsTypesMetricsPartialUpdateBodyNameMax = 255

export const groupsTypesMetricsPartialUpdateBodyIntervalMin = -2147483648
export const groupsTypesMetricsPartialUpdateBodyIntervalMax = 2147483647

export const groupsTypesMetricsPartialUpdateBodyMathPropertyMax = 255

export const GroupsTypesMetricsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(groupsTypesMetricsPartialUpdateBodyNameMax).optional(),
    format: zod.enum(['numeric', 'currency']).optional().describe('* `numeric` - numeric\n* `currency` - currency'),
    interval: zod
        .number()
        .min(groupsTypesMetricsPartialUpdateBodyIntervalMin)
        .max(groupsTypesMetricsPartialUpdateBodyIntervalMax)
        .optional()
        .describe('In days'),
    display: zod.enum(['number', 'sparkline']).optional().describe('* `number` - number\n* `sparkline` - sparkline'),
    filters: zod.unknown().optional(),
    math: zod.enum(['count', 'sum']).optional().describe('* `count` - count\n* `sum` - sum'),
    math_property: zod.string().max(groupsTypesMetricsPartialUpdateBodyMathPropertyMax).nullish(),
})
