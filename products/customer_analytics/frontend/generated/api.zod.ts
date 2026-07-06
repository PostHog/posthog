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
            .describe(
                "Identifier linking this account to its source customer — the analytics group key (the customer's organization id), used to match billing and external records. Optional."
            ),
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
                slack_channel_id: zod.string().nullish(),
                usage_dashboard_link: zod.string().nullish(),
            })
            .nullish()
            .describe(
                'Typed account properties: assignment fields (csm, account_executive, account_owner) and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id, slack_channel_id, usage_dashboard_link). Defaults to an empty object. Unknown keys are rejected.'
            ),
        tags: zod
            .array(zod.string())
            .optional()
            .describe('Tag names attached to the account. Pass a list to replace existing tags.'),
    })
    .describe('A Customer Analytics account — a logical grouping used to assign customer-success ownership.')

export const AccountsCustomPropertyValuesCreateBody = /* @__PURE__ */ zod.object({
    definition: zod.uuid().describe('UUID of the custom property definition whose value to set for this account.'),
    value: zod
        .union([zod.string(), zod.number(), zod.boolean()])
        .describe(
            "Value to store, matching the definition's type: a number for number\/currency\/percent, a boolean for boolean, an ISO-8601 string for date\/datetime, or text for text properties."
        ),
})

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
            .describe(
                "Identifier linking this account to its source customer — the analytics group key (the customer's organization id), used to match billing and external records. Optional."
            ),
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
                slack_channel_id: zod.string().nullish(),
                usage_dashboard_link: zod.string().nullish(),
            })
            .nullish()
            .describe(
                'Typed account properties: assignment fields (csm, account_executive, account_owner) and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id, slack_channel_id, usage_dashboard_link). Defaults to an empty object. Unknown keys are rejected.'
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
            .describe(
                "Identifier linking this account to its source customer — the analytics group key (the customer's organization id), used to match billing and external records. Optional."
            ),
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
                slack_channel_id: zod.string().nullish(),
                usage_dashboard_link: zod.string().nullish(),
            })
            .nullish()
            .describe(
                'Typed account properties: assignment fields (csm, account_executive, account_owner) and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id, slack_channel_id, usage_dashboard_link). Defaults to an empty object. Unknown keys are rejected.'
            ),
        tags: zod
            .array(zod.string())
            .optional()
            .describe('Tag names attached to the account. Pass a list to replace existing tags.'),
    })
    .describe('A Customer Analytics account — a logical grouping used to assign customer-success ownership.')

export const customPropertyDefinitionsCreateBodyNameMax = 400

export const customPropertyDefinitionsCreateBodyIsBigNumberDefault = false
export const customPropertyDefinitionsCreateBodyOptionsItemLabelMax = 400

export const CustomPropertyDefinitionsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(customPropertyDefinitionsCreateBodyNameMax)
            .describe('Human-readable name of the custom property. Unique within the team.'),
        description: zod.string().nullish().describe('Optional description of what the property represents.'),
        display_type: zod
            .enum(['text', 'number', 'currency', 'percent', 'date', 'datetime', 'boolean', 'select'])
            .describe(
                '\* `text` - text\n\* `number` - number\n\* `currency` - currency\n\* `percent` - percent\n\* `date` - date\n\* `datetime` - datetime\n\* `boolean` - boolean\n\* `select` - select'
            )
            .describe(
                "How the property is interpreted and rendered: 'text', 'number', 'currency', 'percent', 'date', 'datetime', 'boolean', or 'select'.\n\n\* `text` - text\n\* `number` - number\n\* `currency` - currency\n\* `percent` - percent\n\* `date` - date\n\* `datetime` - datetime\n\* `boolean` - boolean\n\* `select` - select"
            ),
        is_big_number: zod
            .boolean()
            .default(customPropertyDefinitionsCreateBodyIsBigNumberDefault)
            .describe('Abbreviate large numbers (e.g. 10,000 → 10K). Only applies to numeric properties.'),
        options: zod
            .array(
                zod
                    .object({
                        id: zod
                            .string()
                            .nullish()
                            .describe(
                                'Server-assigned stable id of the option. Omit for new options; send it back unchanged when editing so renames and removals can be told apart.'
                            ),
                        label: zod
                            .string()
                            .max(customPropertyDefinitionsCreateBodyOptionsItemLabelMax)
                            .describe("Display label of the option. Stored as the account's value when picked."),
                        color: zod
                            .enum([
                                'preset-1',
                                'preset-2',
                                'preset-3',
                                'preset-4',
                                'preset-5',
                                'preset-6',
                                'preset-7',
                                'preset-8',
                                'preset-9',
                                'preset-10',
                            ])
                            .describe(
                                '\* `preset-1` - preset-1\n\* `preset-2` - preset-2\n\* `preset-3` - preset-3\n\* `preset-4` - preset-4\n\* `preset-5` - preset-5\n\* `preset-6` - preset-6\n\* `preset-7` - preset-7\n\* `preset-8` - preset-8\n\* `preset-9` - preset-9\n\* `preset-10` - preset-10'
                            )
                            .describe(
                                "Preset color token used to render the option ('preset-1' through 'preset-10').\n\n\* `preset-1` - preset-1\n\* `preset-2` - preset-2\n\* `preset-3` - preset-3\n\* `preset-4` - preset-4\n\* `preset-5` - preset-5\n\* `preset-6` - preset-6\n\* `preset-7` - preset-7\n\* `preset-8` - preset-8\n\* `preset-9` - preset-9\n\* `preset-10` - preset-10"
                            ),
                    })
                    .describe('An allowed value of a select custom property.')
            )
            .nullish()
            .describe(
                "For select properties: the allowed options. Required (non-empty) when display_type is 'select'; cleared server-side for other types."
            ),
    })
    .describe(
        "A team-scoped definition of a custom account property — the attribute side of the model.\n\nHolds only the property's shape (name, display type, big-number flag). Per-account values are\nstored separately, so this serializer never reads or writes account values."
    )

export const customPropertyDefinitionsUpdateBodyNameMax = 400

export const customPropertyDefinitionsUpdateBodyIsBigNumberDefault = false
export const customPropertyDefinitionsUpdateBodyOptionsItemLabelMax = 400

export const CustomPropertyDefinitionsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(customPropertyDefinitionsUpdateBodyNameMax)
            .describe('Human-readable name of the custom property. Unique within the team.'),
        description: zod.string().nullish().describe('Optional description of what the property represents.'),
        display_type: zod
            .enum(['text', 'number', 'currency', 'percent', 'date', 'datetime', 'boolean', 'select'])
            .describe(
                '\* `text` - text\n\* `number` - number\n\* `currency` - currency\n\* `percent` - percent\n\* `date` - date\n\* `datetime` - datetime\n\* `boolean` - boolean\n\* `select` - select'
            )
            .describe(
                "How the property is interpreted and rendered: 'text', 'number', 'currency', 'percent', 'date', 'datetime', 'boolean', or 'select'.\n\n\* `text` - text\n\* `number` - number\n\* `currency` - currency\n\* `percent` - percent\n\* `date` - date\n\* `datetime` - datetime\n\* `boolean` - boolean\n\* `select` - select"
            ),
        is_big_number: zod
            .boolean()
            .default(customPropertyDefinitionsUpdateBodyIsBigNumberDefault)
            .describe('Abbreviate large numbers (e.g. 10,000 → 10K). Only applies to numeric properties.'),
        options: zod
            .array(
                zod
                    .object({
                        id: zod
                            .string()
                            .nullish()
                            .describe(
                                'Server-assigned stable id of the option. Omit for new options; send it back unchanged when editing so renames and removals can be told apart.'
                            ),
                        label: zod
                            .string()
                            .max(customPropertyDefinitionsUpdateBodyOptionsItemLabelMax)
                            .describe("Display label of the option. Stored as the account's value when picked."),
                        color: zod
                            .enum([
                                'preset-1',
                                'preset-2',
                                'preset-3',
                                'preset-4',
                                'preset-5',
                                'preset-6',
                                'preset-7',
                                'preset-8',
                                'preset-9',
                                'preset-10',
                            ])
                            .describe(
                                '\* `preset-1` - preset-1\n\* `preset-2` - preset-2\n\* `preset-3` - preset-3\n\* `preset-4` - preset-4\n\* `preset-5` - preset-5\n\* `preset-6` - preset-6\n\* `preset-7` - preset-7\n\* `preset-8` - preset-8\n\* `preset-9` - preset-9\n\* `preset-10` - preset-10'
                            )
                            .describe(
                                "Preset color token used to render the option ('preset-1' through 'preset-10').\n\n\* `preset-1` - preset-1\n\* `preset-2` - preset-2\n\* `preset-3` - preset-3\n\* `preset-4` - preset-4\n\* `preset-5` - preset-5\n\* `preset-6` - preset-6\n\* `preset-7` - preset-7\n\* `preset-8` - preset-8\n\* `preset-9` - preset-9\n\* `preset-10` - preset-10"
                            ),
                    })
                    .describe('An allowed value of a select custom property.')
            )
            .nullish()
            .describe(
                "For select properties: the allowed options. Required (non-empty) when display_type is 'select'; cleared server-side for other types."
            ),
    })
    .describe(
        "A team-scoped definition of a custom account property — the attribute side of the model.\n\nHolds only the property's shape (name, display type, big-number flag). Per-account values are\nstored separately, so this serializer never reads or writes account values."
    )

export const customPropertyDefinitionsPartialUpdateBodyNameMax = 400

export const customPropertyDefinitionsPartialUpdateBodyIsBigNumberDefault = false
export const customPropertyDefinitionsPartialUpdateBodyOptionsItemLabelMax = 400

export const CustomPropertyDefinitionsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(customPropertyDefinitionsPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable name of the custom property. Unique within the team.'),
        description: zod.string().nullish().describe('Optional description of what the property represents.'),
        display_type: zod
            .enum(['text', 'number', 'currency', 'percent', 'date', 'datetime', 'boolean', 'select'])
            .describe(
                '\* `text` - text\n\* `number` - number\n\* `currency` - currency\n\* `percent` - percent\n\* `date` - date\n\* `datetime` - datetime\n\* `boolean` - boolean\n\* `select` - select'
            )
            .optional()
            .describe(
                "How the property is interpreted and rendered: 'text', 'number', 'currency', 'percent', 'date', 'datetime', 'boolean', or 'select'.\n\n\* `text` - text\n\* `number` - number\n\* `currency` - currency\n\* `percent` - percent\n\* `date` - date\n\* `datetime` - datetime\n\* `boolean` - boolean\n\* `select` - select"
            ),
        is_big_number: zod
            .boolean()
            .default(customPropertyDefinitionsPartialUpdateBodyIsBigNumberDefault)
            .describe('Abbreviate large numbers (e.g. 10,000 → 10K). Only applies to numeric properties.'),
        options: zod
            .array(
                zod
                    .object({
                        id: zod
                            .string()
                            .nullish()
                            .describe(
                                'Server-assigned stable id of the option. Omit for new options; send it back unchanged when editing so renames and removals can be told apart.'
                            ),
                        label: zod
                            .string()
                            .max(customPropertyDefinitionsPartialUpdateBodyOptionsItemLabelMax)
                            .describe("Display label of the option. Stored as the account's value when picked."),
                        color: zod
                            .enum([
                                'preset-1',
                                'preset-2',
                                'preset-3',
                                'preset-4',
                                'preset-5',
                                'preset-6',
                                'preset-7',
                                'preset-8',
                                'preset-9',
                                'preset-10',
                            ])
                            .describe(
                                '\* `preset-1` - preset-1\n\* `preset-2` - preset-2\n\* `preset-3` - preset-3\n\* `preset-4` - preset-4\n\* `preset-5` - preset-5\n\* `preset-6` - preset-6\n\* `preset-7` - preset-7\n\* `preset-8` - preset-8\n\* `preset-9` - preset-9\n\* `preset-10` - preset-10'
                            )
                            .describe(
                                "Preset color token used to render the option ('preset-1' through 'preset-10').\n\n\* `preset-1` - preset-1\n\* `preset-2` - preset-2\n\* `preset-3` - preset-3\n\* `preset-4` - preset-4\n\* `preset-5` - preset-5\n\* `preset-6` - preset-6\n\* `preset-7` - preset-7\n\* `preset-8` - preset-8\n\* `preset-9` - preset-9\n\* `preset-10` - preset-10"
                            ),
                    })
                    .describe('An allowed value of a select custom property.')
            )
            .nullish()
            .describe(
                "For select properties: the allowed options. Required (non-empty) when display_type is 'select'; cleared server-side for other types."
            ),
    })
    .describe(
        "A team-scoped definition of a custom account property — the attribute side of the model.\n\nHolds only the property's shape (name, display type, big-number flag). Per-account values are\nstored separately, so this serializer never reads or writes account values."
    )

export const customPropertySourcesCreateBodySourceColumnMax = 400

export const customPropertySourcesCreateBodyKeyColumnMax = 400

export const customPropertySourcesCreateBodyIsEnabledDefault = true

export const CustomPropertySourcesCreateBody = /* @__PURE__ */ zod
    .object({
        definition: zod
            .uuid()
            .describe('UUID of the custom property definition this source feeds. One source per definition.'),
        saved_query: zod
            .uuid()
            .describe('UUID of the data-warehouse saved query (materialized view) to read values from.'),
        source_column: zod
            .string()
            .max(customPropertySourcesCreateBodySourceColumnMax)
            .describe('Column in the view whose value is written to the property.'),
        key_column: zod
            .string()
            .max(customPropertySourcesCreateBodyKeyColumnMax)
            .describe("Column in the view whose value matches an account's external_id."),
        is_enabled: zod
            .boolean()
            .default(customPropertySourcesCreateBodyIsEnabledDefault)
            .describe(
                'Whether the source syncs. Auto-disabled after repeated failures or a missing view; re-enabling resets the failure count.'
            ),
    })
    .describe(
        "Binds a materialized data-warehouse view column to a custom property definition; the view's\nvalues are synced onto matching accounts on each materialization."
    )

export const customPropertySourcesUpdateBodySourceColumnMax = 400

export const customPropertySourcesUpdateBodyKeyColumnMax = 400

export const CustomPropertySourcesUpdateBody = /* @__PURE__ */ zod
    .object({
        source_column: zod
            .string()
            .max(customPropertySourcesUpdateBodySourceColumnMax)
            .optional()
            .describe('Column in the view whose value is written to the property.'),
        key_column: zod
            .string()
            .max(customPropertySourcesUpdateBodyKeyColumnMax)
            .optional()
            .describe("Column in the view whose value matches an account's external_id."),
        is_enabled: zod
            .boolean()
            .optional()
            .describe('Whether the source syncs; re-enabling it resets the failure count.'),
    })
    .describe(
        "Writable fields for updating a source. ``definition`` and ``saved_query`` are create-only, so\nthey are intentionally absent — only these reach the facade's update."
    )

export const customPropertySourcesPartialUpdateBodySourceColumnMax = 400

export const customPropertySourcesPartialUpdateBodyKeyColumnMax = 400

export const CustomPropertySourcesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        source_column: zod
            .string()
            .max(customPropertySourcesPartialUpdateBodySourceColumnMax)
            .optional()
            .describe('Column in the view whose value is written to the property.'),
        key_column: zod
            .string()
            .max(customPropertySourcesPartialUpdateBodyKeyColumnMax)
            .optional()
            .describe("Column in the view whose value matches an account's external_id."),
        is_enabled: zod
            .boolean()
            .optional()
            .describe('Whether the source syncs; re-enabling it resets the failure count.'),
    })
    .describe(
        "Writable fields for updating a source. ``definition`` and ``saved_query`` are create-only, so\nthey are intentionally absent — only these reach the facade's update."
    )

export const customerJourneysCreateBodyNameMax = 400

export const CustomerJourneysCreateBody = /* @__PURE__ */ zod.object({
    insight: zod.number(),
    name: zod.string().max(customerJourneysCreateBodyNameMax),
    description: zod.string().nullish(),
})

export const customerJourneysUpdateBodyNameMax = 400

export const CustomerJourneysUpdateBody = /* @__PURE__ */ zod.object({
    insight: zod.number(),
    name: zod.string().max(customerJourneysUpdateBodyNameMax),
    description: zod.string().nullish(),
})

export const customerJourneysPartialUpdateBodyNameMax = 400

export const CustomerJourneysPartialUpdateBody = /* @__PURE__ */ zod.object({
    insight: zod.number().optional(),
    name: zod.string().max(customerJourneysPartialUpdateBodyNameMax).optional(),
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

export const CustomerProfileConfigsUpdateBody = /* @__PURE__ */ zod.object({
    scope: zod
        .enum(['person', 'group_0', 'group_1', 'group_2', 'group_3', 'group_4'])
        .describe(
            '\* `person` - Person\n\* `group_0` - Group 0\n\* `group_1` - Group 1\n\* `group_2` - Group 2\n\* `group_3` - Group 3\n\* `group_4` - Group 4'
        ),
    content: zod.unknown().optional(),
    sidebar: zod.unknown().optional(),
})

export const CustomerProfileConfigsPartialUpdateBody = /* @__PURE__ */ zod.object({
    scope: zod
        .enum(['person', 'group_0', 'group_1', 'group_2', 'group_3', 'group_4'])
        .optional()
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
