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

export const accountsCreateBodyNameMax = 400

export const accountsCreateBodyExternalIdMax = 400

export const AccountsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(accountsCreateBodyNameMax).describe('Human-readable name of the account.'),
        external_id: zod
            .string()
            .max(accountsCreateBodyExternalIdMax)
            .nullish()
            .describe('Identifier for the account in an external system (e.g. CRM ID). Optional.'),
        properties: zod
            .object({
                csm: zod
                    .object({
                        id: zod.number(),
                        email: zod.string(),
                    })
                    .nullish(),
                account_executive: zod
                    .object({
                        id: zod.number(),
                        email: zod.string(),
                    })
                    .nullish(),
                account_owner: zod
                    .object({
                        id: zod.number(),
                        email: zod.string(),
                    })
                    .nullish(),
                stripe_customer_id: zod.string().nullish(),
                hubspot_deal_id: zod.string().nullish(),
                billing_id: zod.string().nullish(),
                sfdc_id: zod.string().nullish(),
                zendesk_id: zod.string().nullish(),
            })
            .nullish()
            .describe(
                'Typed account properties: assignment fields (csm, account_executive, account_owner) and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id). Defaults to an empty object. Unknown keys are rejected.'
            ),
        tags: zod
            .array(zod.string())
            .optional()
            .describe('Tag names attached to the account. Pass a list to replace existing tags.'),
    })
    .describe('A Customer Analytics account — a logical grouping used to assign customer-success ownership.')

export const accountsNotebooksCreateBodyTitleMax = 256

export const AccountsNotebooksCreateBody = /* @__PURE__ */ zod.object({
    title: zod
        .string()
        .max(accountsNotebooksCreateBodyTitleMax)
        .nullish()
        .describe('Human-readable title of the account notebook.'),
    content: zod.unknown().optional().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
})

export const accountsUpdateBodyNameMax = 400

export const accountsUpdateBodyExternalIdMax = 400

export const AccountsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(accountsUpdateBodyNameMax).describe('Human-readable name of the account.'),
        external_id: zod
            .string()
            .max(accountsUpdateBodyExternalIdMax)
            .nullish()
            .describe('Identifier for the account in an external system (e.g. CRM ID). Optional.'),
        properties: zod
            .object({
                csm: zod
                    .object({
                        id: zod.number(),
                        email: zod.string(),
                    })
                    .nullish(),
                account_executive: zod
                    .object({
                        id: zod.number(),
                        email: zod.string(),
                    })
                    .nullish(),
                account_owner: zod
                    .object({
                        id: zod.number(),
                        email: zod.string(),
                    })
                    .nullish(),
                stripe_customer_id: zod.string().nullish(),
                hubspot_deal_id: zod.string().nullish(),
                billing_id: zod.string().nullish(),
                sfdc_id: zod.string().nullish(),
                zendesk_id: zod.string().nullish(),
            })
            .nullish()
            .describe(
                'Typed account properties: assignment fields (csm, account_executive, account_owner) and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id). Defaults to an empty object. Unknown keys are rejected.'
            ),
        tags: zod
            .array(zod.string())
            .optional()
            .describe('Tag names attached to the account. Pass a list to replace existing tags.'),
    })
    .describe('A Customer Analytics account — a logical grouping used to assign customer-success ownership.')

export const accountsPartialUpdateBodyNameMax = 400

export const accountsPartialUpdateBodyExternalIdMax = 400

export const AccountsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(accountsPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable name of the account.'),
        external_id: zod
            .string()
            .max(accountsPartialUpdateBodyExternalIdMax)
            .nullish()
            .describe('Identifier for the account in an external system (e.g. CRM ID). Optional.'),
        properties: zod
            .object({
                csm: zod
                    .object({
                        id: zod.number(),
                        email: zod.string(),
                    })
                    .nullish(),
                account_executive: zod
                    .object({
                        id: zod.number(),
                        email: zod.string(),
                    })
                    .nullish(),
                account_owner: zod
                    .object({
                        id: zod.number(),
                        email: zod.string(),
                    })
                    .nullish(),
                stripe_customer_id: zod.string().nullish(),
                hubspot_deal_id: zod.string().nullish(),
                billing_id: zod.string().nullish(),
                sfdc_id: zod.string().nullish(),
                zendesk_id: zod.string().nullish(),
            })
            .nullish()
            .describe(
                'Typed account properties: assignment fields (csm, account_executive, account_owner) and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id). Defaults to an empty object. Unknown keys are rejected.'
            ),
        tags: zod
            .array(zod.string())
            .optional()
            .describe('Tag names attached to the account. Pass a list to replace existing tags.'),
    })
    .describe('A Customer Analytics account — a logical grouping used to assign customer-success ownership.')

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
            '\* `person` - Person\n\* `group_0` - Group 0\n\* `group_1` - Group 1\n\* `group_2` - Group 2\n\* `group_3` - Group 3\n\* `group_4` - Group 4'
        ),
    content: zod.unknown().optional(),
    sidebar: zod.unknown().optional(),
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
        .describe('\* `numeric` - numeric\n\* `currency` - currency')
        .default(groupsTypesMetricsCreateBodyFormatDefault)
        .describe(
            'How the metric value is formatted in the UI. One of `numeric` or `currency`.\n\n\* `numeric` - numeric\n\* `currency` - currency'
        ),
    interval: zod
        .number()
        .default(groupsTypesMetricsCreateBodyIntervalDefault)
        .describe('Rolling time window in days used to compute the metric. Defaults to 7.'),
    display: zod
        .enum(['number', 'sparkline'])
        .describe('\* `number` - number\n\* `sparkline` - sparkline')
        .default(groupsTypesMetricsCreateBodyDisplayDefault)
        .describe(
            'Visual representation in the UI. One of `number` or `sparkline`.\n\n\* `number` - number\n\* `sparkline` - sparkline'
        ),
    filters: zod
        .record(zod.string(), zod.unknown())
        .describe(
            'Filter definition for the metric. Two shapes are accepted, discriminated by an optional `source` key.\n\n\*\*Events\*\* (default, when `source` is missing or `\"events\"`): HogFunction filter shape — `events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.\n\n\*\*Data warehouse\*\* (`source: \"data_warehouse\"`): `table_name` (synced DW table), `timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value matches the entity key). Currently DW metrics only render on group profiles — person profiles are not yet supported.'
        ),
    math: zod
        .enum(['count', 'sum'])
        .describe('\* `count` - count\n\* `sum` - sum')
        .default(groupsTypesMetricsCreateBodyMathDefault)
        .describe(
            'Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` on matching events.\n\n\* `count` - count\n\* `sum` - sum'
        ),
    math_property: zod
        .string()
        .max(groupsTypesMetricsCreateBodyMathPropertyMax)
        .nullish()
        .describe(
            'Required when `math` is `sum`; must be empty when `math` is `count`. For events metrics this is an event property name. For data warehouse metrics this is the column name (or HogQL expression) to sum on the DW table.'
        ),
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
        .describe('\* `numeric` - numeric\n\* `currency` - currency')
        .default(groupsTypesMetricsUpdateBodyFormatDefault)
        .describe(
            'How the metric value is formatted in the UI. One of `numeric` or `currency`.\n\n\* `numeric` - numeric\n\* `currency` - currency'
        ),
    interval: zod
        .number()
        .default(groupsTypesMetricsUpdateBodyIntervalDefault)
        .describe('Rolling time window in days used to compute the metric. Defaults to 7.'),
    display: zod
        .enum(['number', 'sparkline'])
        .describe('\* `number` - number\n\* `sparkline` - sparkline')
        .default(groupsTypesMetricsUpdateBodyDisplayDefault)
        .describe(
            'Visual representation in the UI. One of `number` or `sparkline`.\n\n\* `number` - number\n\* `sparkline` - sparkline'
        ),
    filters: zod
        .record(zod.string(), zod.unknown())
        .describe(
            'Filter definition for the metric. Two shapes are accepted, discriminated by an optional `source` key.\n\n\*\*Events\*\* (default, when `source` is missing or `\"events\"`): HogFunction filter shape — `events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.\n\n\*\*Data warehouse\*\* (`source: \"data_warehouse\"`): `table_name` (synced DW table), `timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value matches the entity key). Currently DW metrics only render on group profiles — person profiles are not yet supported.'
        ),
    math: zod
        .enum(['count', 'sum'])
        .describe('\* `count` - count\n\* `sum` - sum')
        .default(groupsTypesMetricsUpdateBodyMathDefault)
        .describe(
            'Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` on matching events.\n\n\* `count` - count\n\* `sum` - sum'
        ),
    math_property: zod
        .string()
        .max(groupsTypesMetricsUpdateBodyMathPropertyMax)
        .nullish()
        .describe(
            'Required when `math` is `sum`; must be empty when `math` is `count`. For events metrics this is an event property name. For data warehouse metrics this is the column name (or HogQL expression) to sum on the DW table.'
        ),
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
        .describe('\* `numeric` - numeric\n\* `currency` - currency')
        .default(groupsTypesMetricsPartialUpdateBodyFormatDefault)
        .describe(
            'How the metric value is formatted in the UI. One of `numeric` or `currency`.\n\n\* `numeric` - numeric\n\* `currency` - currency'
        ),
    interval: zod
        .number()
        .default(groupsTypesMetricsPartialUpdateBodyIntervalDefault)
        .describe('Rolling time window in days used to compute the metric. Defaults to 7.'),
    display: zod
        .enum(['number', 'sparkline'])
        .describe('\* `number` - number\n\* `sparkline` - sparkline')
        .default(groupsTypesMetricsPartialUpdateBodyDisplayDefault)
        .describe(
            'Visual representation in the UI. One of `number` or `sparkline`.\n\n\* `number` - number\n\* `sparkline` - sparkline'
        ),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Filter definition for the metric. Two shapes are accepted, discriminated by an optional `source` key.\n\n\*\*Events\*\* (default, when `source` is missing or `\"events\"`): HogFunction filter shape — `events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.\n\n\*\*Data warehouse\*\* (`source: \"data_warehouse\"`): `table_name` (synced DW table), `timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value matches the entity key). Currently DW metrics only render on group profiles — person profiles are not yet supported.'
        ),
    math: zod
        .enum(['count', 'sum'])
        .describe('\* `count` - count\n\* `sum` - sum')
        .default(groupsTypesMetricsPartialUpdateBodyMathDefault)
        .describe(
            'Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` on matching events.\n\n\* `count` - count\n\* `sum` - sum'
        ),
    math_property: zod
        .string()
        .max(groupsTypesMetricsPartialUpdateBodyMathPropertyMax)
        .nullish()
        .describe(
            'Required when `math` is `sum`; must be empty when `math` is `count`. For events metrics this is an event property name. For data warehouse metrics this is the column name (or HogQL expression) to sum on the DW table.'
        ),
})
