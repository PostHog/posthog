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

export const groupsTypesMetricsCreateBodyFormatDefault = `numeric`
export const groupsTypesMetricsCreateBodyIntervalDefault = 7
export const groupsTypesMetricsCreateBodyDisplayDefault = `number`
export const groupsTypesMetricsCreateBodyMathDefault = `count`
export const groupsTypesMetricsCreateBodyMathPropertyMax = 255

export const GroupsTypesMetricsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(groupsTypesMetricsCreateBodyNameMax)
        .describe('Name of the usage metric. Must be unique per group type within the project.'),
    format: zod
        .enum(['numeric', 'currency'])
        .describe('* `numeric` - numeric\n* `currency` - currency')
        .default(groupsTypesMetricsCreateBodyFormatDefault)
        .describe(
            'How the metric value is formatted in the UI. One of `numeric` or `currency`.\n\n* `numeric` - numeric\n* `currency` - currency'
        ),
    interval: zod
        .number()
        .default(groupsTypesMetricsCreateBodyIntervalDefault)
        .describe('Rolling time window in days used to compute the metric. Defaults to 7.'),
    display: zod
        .enum(['number', 'sparkline'])
        .describe('* `number` - number\n* `sparkline` - sparkline')
        .default(groupsTypesMetricsCreateBodyDisplayDefault)
        .describe(
            'Visual representation in the UI. One of `number` or `sparkline`.\n\n* `number` - number\n* `sparkline` - sparkline'
        ),
    filters: zod
        .record(zod.string(), zod.unknown())
        .describe(
            'HogQL filter definition used to compute the metric. Same shape as HogFunction filters: a dict containing an `events` list and optional `properties` list.'
        ),
    math: zod
        .enum(['count', 'sum'])
        .describe('* `count` - count\n* `sum` - sum')
        .default(groupsTypesMetricsCreateBodyMathDefault)
        .describe(
            'Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` on matching events.\n\n* `count` - count\n* `sum` - sum'
        ),
    math_property: zod
        .string()
        .max(groupsTypesMetricsCreateBodyMathPropertyMax)
        .nullish()
        .describe('Event property to sum. Required when `math` is `sum` and forbidden when `math` is `count`.'),
})

export const groupsTypesMetricsUpdateBodyNameMax = 255

export const groupsTypesMetricsUpdateBodyFormatDefault = `numeric`
export const groupsTypesMetricsUpdateBodyIntervalDefault = 7
export const groupsTypesMetricsUpdateBodyDisplayDefault = `number`
export const groupsTypesMetricsUpdateBodyMathDefault = `count`
export const groupsTypesMetricsUpdateBodyMathPropertyMax = 255

export const GroupsTypesMetricsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(groupsTypesMetricsUpdateBodyNameMax)
        .describe('Name of the usage metric. Must be unique per group type within the project.'),
    format: zod
        .enum(['numeric', 'currency'])
        .describe('* `numeric` - numeric\n* `currency` - currency')
        .default(groupsTypesMetricsUpdateBodyFormatDefault)
        .describe(
            'How the metric value is formatted in the UI. One of `numeric` or `currency`.\n\n* `numeric` - numeric\n* `currency` - currency'
        ),
    interval: zod
        .number()
        .default(groupsTypesMetricsUpdateBodyIntervalDefault)
        .describe('Rolling time window in days used to compute the metric. Defaults to 7.'),
    display: zod
        .enum(['number', 'sparkline'])
        .describe('* `number` - number\n* `sparkline` - sparkline')
        .default(groupsTypesMetricsUpdateBodyDisplayDefault)
        .describe(
            'Visual representation in the UI. One of `number` or `sparkline`.\n\n* `number` - number\n* `sparkline` - sparkline'
        ),
    filters: zod
        .record(zod.string(), zod.unknown())
        .describe(
            'HogQL filter definition used to compute the metric. Same shape as HogFunction filters: a dict containing an `events` list and optional `properties` list.'
        ),
    math: zod
        .enum(['count', 'sum'])
        .describe('* `count` - count\n* `sum` - sum')
        .default(groupsTypesMetricsUpdateBodyMathDefault)
        .describe(
            'Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` on matching events.\n\n* `count` - count\n* `sum` - sum'
        ),
    math_property: zod
        .string()
        .max(groupsTypesMetricsUpdateBodyMathPropertyMax)
        .nullish()
        .describe('Event property to sum. Required when `math` is `sum` and forbidden when `math` is `count`.'),
})

export const groupsTypesMetricsPartialUpdateBodyNameMax = 255

export const groupsTypesMetricsPartialUpdateBodyFormatDefault = `numeric`
export const groupsTypesMetricsPartialUpdateBodyIntervalDefault = 7
export const groupsTypesMetricsPartialUpdateBodyDisplayDefault = `number`
export const groupsTypesMetricsPartialUpdateBodyMathDefault = `count`
export const groupsTypesMetricsPartialUpdateBodyMathPropertyMax = 255

export const GroupsTypesMetricsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(groupsTypesMetricsPartialUpdateBodyNameMax)
        .optional()
        .describe('Name of the usage metric. Must be unique per group type within the project.'),
    format: zod
        .enum(['numeric', 'currency'])
        .describe('* `numeric` - numeric\n* `currency` - currency')
        .default(groupsTypesMetricsPartialUpdateBodyFormatDefault)
        .describe(
            'How the metric value is formatted in the UI. One of `numeric` or `currency`.\n\n* `numeric` - numeric\n* `currency` - currency'
        ),
    interval: zod
        .number()
        .default(groupsTypesMetricsPartialUpdateBodyIntervalDefault)
        .describe('Rolling time window in days used to compute the metric. Defaults to 7.'),
    display: zod
        .enum(['number', 'sparkline'])
        .describe('* `number` - number\n* `sparkline` - sparkline')
        .default(groupsTypesMetricsPartialUpdateBodyDisplayDefault)
        .describe(
            'Visual representation in the UI. One of `number` or `sparkline`.\n\n* `number` - number\n* `sparkline` - sparkline'
        ),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'HogQL filter definition used to compute the metric. Same shape as HogFunction filters: a dict containing an `events` list and optional `properties` list.'
        ),
    math: zod
        .enum(['count', 'sum'])
        .describe('* `count` - count\n* `sum` - sum')
        .default(groupsTypesMetricsPartialUpdateBodyMathDefault)
        .describe(
            'Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` on matching events.\n\n* `count` - count\n* `sum` - sum'
        ),
    math_property: zod
        .string()
        .max(groupsTypesMetricsPartialUpdateBodyMathPropertyMax)
        .nullish()
        .describe('Event property to sum. Required when `math` is `sum` and forbidden when `math` is `count`.'),
})
