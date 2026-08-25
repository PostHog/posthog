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

export const accountRelationshipDefinitionsCreateBodyNameMax = 400

export const accountRelationshipDefinitionsCreateBodyIsSingleHolderDefault = true

export const AccountRelationshipDefinitionsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(accountRelationshipDefinitionsCreateBodyNameMax)
            .describe('Human-readable name of the relationship. Unique within the team.'),
        description: zod
            .string()
            .nullish()
            .describe(
                "What this relationship means, e.g. 'The customer success manager responsible for this account'."
            ),
        is_single_holder: zod
            .boolean()
            .default(accountRelationshipDefinitionsCreateBodyIsSingleHolderDefault)
            .describe(
                'Whether only one user can hold this relationship per account at a time, e.g. a single CSM per account.'
            ),
    })
    .describe('A team-defined account relationship type (CSM, Onboarding manager, ...).')

export const accountRelationshipDefinitionsUpdateBodyNameMax = 400

export const accountRelationshipDefinitionsUpdateBodyIsSingleHolderDefault = true

export const AccountRelationshipDefinitionsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(accountRelationshipDefinitionsUpdateBodyNameMax)
            .describe('Human-readable name of the relationship. Unique within the team.'),
        description: zod
            .string()
            .nullish()
            .describe(
                "What this relationship means, e.g. 'The customer success manager responsible for this account'."
            ),
        is_single_holder: zod
            .boolean()
            .default(accountRelationshipDefinitionsUpdateBodyIsSingleHolderDefault)
            .describe(
                'Whether only one user can hold this relationship per account at a time, e.g. a single CSM per account.'
            ),
    })
    .describe('A team-defined account relationship type (CSM, Onboarding manager, ...).')

export const accountRelationshipDefinitionsPartialUpdateBodyNameMax = 400

export const accountRelationshipDefinitionsPartialUpdateBodyIsSingleHolderDefault = true

export const AccountRelationshipDefinitionsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(accountRelationshipDefinitionsPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable name of the relationship. Unique within the team.'),
        description: zod
            .string()
            .nullish()
            .describe(
                "What this relationship means, e.g. 'The customer success manager responsible for this account'."
            ),
        is_single_holder: zod
            .boolean()
            .default(accountRelationshipDefinitionsPartialUpdateBodyIsSingleHolderDefault)
            .describe(
                'Whether only one user can hold this relationship per account at a time, e.g. a single CSM per account.'
            ),
    })
    .describe('A team-defined account relationship type (CSM, Onboarding manager, ...).')

export const accountTrackRulesUpdateBodyVersionMin = 0

export const AccountTrackRulesUpdateBody = /* @__PURE__ */ zod.object({
    schema_version: zod.number(),
    version: zod.number().min(accountTrackRulesUpdateBodyVersionMin),
    enabled: zod.boolean(),
    groups: zod.array(
        zod.object({
            conditions: zod.array(
                zod.object({
                    field: zod.object({
                        kind: zod
                            .enum(['account_field', 'custom_property'])
                            .describe('\* `account_field` - account_field\n\* `custom_property` - custom_property'),
                        field: zod
                            .union([
                                zod
                                    .enum([
                                        'name',
                                        'external_id',
                                        'created_at',
                                        'updated_at',
                                        'churned_at',
                                        'ignored_at',
                                        'stripe_customer_id',
                                        'hubspot_deal_id',
                                        'billing_id',
                                        'sfdc_id',
                                        'zendesk_id',
                                    ])
                                    .describe(
                                        '\* `name` - name\n\* `external_id` - external_id\n\* `created_at` - created_at\n\* `updated_at` - updated_at\n\* `churned_at` - churned_at\n\* `ignored_at` - ignored_at\n\* `stripe_customer_id` - stripe_customer_id\n\* `hubspot_deal_id` - hubspot_deal_id\n\* `billing_id` - billing_id\n\* `sfdc_id` - sfdc_id\n\* `zendesk_id` - zendesk_id'
                                    ),
                                zod.null(),
                            ])
                            .optional(),
                        definition_id: zod.uuid().nullish(),
                    }),
                    operator: zod.string(),
                    values: zod.array(zod.unknown()).optional(),
                })
            ),
        })
    ),
})

export const accountTrackRulesPreviewCreateBodyVersionMin = 0

export const AccountTrackRulesPreviewCreateBody = /* @__PURE__ */ zod.object({
    schema_version: zod.number(),
    version: zod.number().min(accountTrackRulesPreviewCreateBodyVersionMin),
    enabled: zod.boolean(),
    groups: zod.array(
        zod.object({
            conditions: zod.array(
                zod.object({
                    field: zod.object({
                        kind: zod
                            .enum(['account_field', 'custom_property'])
                            .describe('\* `account_field` - account_field\n\* `custom_property` - custom_property'),
                        field: zod
                            .union([
                                zod
                                    .enum([
                                        'name',
                                        'external_id',
                                        'created_at',
                                        'updated_at',
                                        'churned_at',
                                        'ignored_at',
                                        'stripe_customer_id',
                                        'hubspot_deal_id',
                                        'billing_id',
                                        'sfdc_id',
                                        'zendesk_id',
                                    ])
                                    .describe(
                                        '\* `name` - name\n\* `external_id` - external_id\n\* `created_at` - created_at\n\* `updated_at` - updated_at\n\* `churned_at` - churned_at\n\* `ignored_at` - ignored_at\n\* `stripe_customer_id` - stripe_customer_id\n\* `hubspot_deal_id` - hubspot_deal_id\n\* `billing_id` - billing_id\n\* `sfdc_id` - sfdc_id\n\* `zendesk_id` - zendesk_id'
                                    ),
                                zod.null(),
                            ])
                            .optional(),
                        definition_id: zod.uuid().nullish(),
                    }),
                    operator: zod.string(),
                    values: zod.array(zod.unknown()).optional(),
                })
            ),
        })
    ),
})

export const AccountTrackRulesRunCreateBody = /* @__PURE__ */ zod.object({
    idempotency_key: zod.uuid(),
    confirmed: zod.boolean(),
})

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
                email_domains: zod
                    .array(zod.string())
                    .optional()
                    .describe(
                        "Email domains owned by this account's company, used to match inbound touchpoints to the account."
                    ),
                known_emails: zod
                    .array(zod.string())
                    .optional()
                    .describe('Individual email addresses pinned to this account, matched before the domain fallback.'),
                stripe_customer_id: zod.string().nullish(),
                hubspot_deal_id: zod.string().nullish(),
                billing_id: zod.string().nullish(),
                sfdc_id: zod.string().nullish(),
                zendesk_id: zod.string().nullish(),
                slack_channel_id: zod.string().nullish(),
                usage_dashboard_link: zod.string().nullish(),
                metabase_link: zod.string().nullish(),
            })
            .nullish()
            .describe(
                "Typed account properties: external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id, slack_channel_id, usage_dashboard_link, metabase_link) plus touchpoint matching lists: email_domains (the company's email domains) and known_emails (individual addresses pinned to the account). Defaults to an empty object. Unknown keys are rejected. User assignments live on account relationships, not here."
            ),
        tags: zod
            .array(zod.string())
            .optional()
            .describe('Tag names attached to the account. Pass a list to replace existing tags.'),
        slack_summary_cadence: zod
            .union([
                zod
                    .enum(['daily', 'weekly', 'monthly'])
                    .describe('\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly'),
                zod.null(),
            ])
            .optional()
            .describe(
                "How often to generate an AI summary of the account's bound Slack channel (daily, weekly, or monthly). Null means summaries are off.\n\n\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly"
            ),
        churned_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('When the account churned. Null means the account has not churned.'),
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

export const AccountsRelationshipsCreateBody = /* @__PURE__ */ zod
    .object({
        definition: zod.uuid().describe('Id of the relationship definition to assign.'),
        user: zod.number().describe("PostHog user id of the assignee. Must be a member of the account's organization."),
    })
    .describe('Input for assigning a user to an account relationship.')

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
                email_domains: zod
                    .array(zod.string())
                    .optional()
                    .describe(
                        "Email domains owned by this account's company, used to match inbound touchpoints to the account."
                    ),
                known_emails: zod
                    .array(zod.string())
                    .optional()
                    .describe('Individual email addresses pinned to this account, matched before the domain fallback.'),
                stripe_customer_id: zod.string().nullish(),
                hubspot_deal_id: zod.string().nullish(),
                billing_id: zod.string().nullish(),
                sfdc_id: zod.string().nullish(),
                zendesk_id: zod.string().nullish(),
                slack_channel_id: zod.string().nullish(),
                usage_dashboard_link: zod.string().nullish(),
                metabase_link: zod.string().nullish(),
            })
            .nullish()
            .describe(
                "Typed account properties: external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id, slack_channel_id, usage_dashboard_link, metabase_link) plus touchpoint matching lists: email_domains (the company's email domains) and known_emails (individual addresses pinned to the account). Defaults to an empty object. Unknown keys are rejected. User assignments live on account relationships, not here."
            ),
        tags: zod
            .array(zod.string())
            .optional()
            .describe('Tag names attached to the account. Pass a list to replace existing tags.'),
        slack_summary_cadence: zod
            .union([
                zod
                    .enum(['daily', 'weekly', 'monthly'])
                    .describe('\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly'),
                zod.null(),
            ])
            .optional()
            .describe(
                "How often to generate an AI summary of the account's bound Slack channel (daily, weekly, or monthly). Null means summaries are off.\n\n\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly"
            ),
        churned_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('When the account churned. Null means the account has not churned.'),
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
                email_domains: zod
                    .array(zod.string())
                    .optional()
                    .describe(
                        "Email domains owned by this account's company, used to match inbound touchpoints to the account."
                    ),
                known_emails: zod
                    .array(zod.string())
                    .optional()
                    .describe('Individual email addresses pinned to this account, matched before the domain fallback.'),
                stripe_customer_id: zod.string().nullish(),
                hubspot_deal_id: zod.string().nullish(),
                billing_id: zod.string().nullish(),
                sfdc_id: zod.string().nullish(),
                zendesk_id: zod.string().nullish(),
                slack_channel_id: zod.string().nullish(),
                usage_dashboard_link: zod.string().nullish(),
                metabase_link: zod.string().nullish(),
            })
            .nullish()
            .describe(
                "Typed account properties: external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id, slack_channel_id, usage_dashboard_link, metabase_link) plus touchpoint matching lists: email_domains (the company's email domains) and known_emails (individual addresses pinned to the account). Defaults to an empty object. Unknown keys are rejected. User assignments live on account relationships, not here."
            ),
        tags: zod
            .array(zod.string())
            .optional()
            .describe('Tag names attached to the account. Pass a list to replace existing tags.'),
        slack_summary_cadence: zod
            .union([
                zod
                    .enum(['daily', 'weekly', 'monthly'])
                    .describe('\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly'),
                zod.null(),
            ])
            .optional()
            .describe(
                "How often to generate an AI summary of the account's bound Slack channel (daily, weekly, or monthly). Null means summaries are off.\n\n\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly"
            ),
        churned_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('When the account churned. Null means the account has not churned.'),
    })
    .describe('A Customer Analytics account — a logical grouping used to assign customer-success ownership.')

export const AnnouncementsCreateBody = /* @__PURE__ */ zod.object({
    message: zod.string().describe('Message body to send, rendered as Slack mrkdwn.'),
    channels: zod
        .array(zod.string())
        .describe(
            'Slack channel IDs to send to. Each must be a channel the SupportHog bot is a member of; names are resolved server-side.'
        ),
})

/**
 * Start a sync run for one connected Google Calendar immediately, outside the hourly schedule.
 * @summary Sync a connected calendar now
 */
export const CalendarSyncSyncNowCreateBody = /* @__PURE__ */ zod
    .object({
        integration_id: zod.number().describe('Id of the google-calendar integration to sync.'),
    })
    .describe('Request body of the calendar sync-now trigger.')

export const customPropertyDefinitionsCreateBodyNameMax = 400

export const customPropertyDefinitionsCreateBodyTargetTypeDefault = `account`
export const customPropertyDefinitionsCreateBodyGroupTypeIndexMin = 0
export const customPropertyDefinitionsCreateBodyGroupTypeIndexMax = 4

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
        target_type: zod
            .enum(['account', 'person', 'group'])
            .describe('\* `account` - account\n\* `person` - person\n\* `group` - group')
            .default(customPropertyDefinitionsCreateBodyTargetTypeDefault)
            .describe(
                "What entity this property is attached to: 'account' (default), 'person', or 'group'. Person and group properties are populated from a warehouse schema and become usable like any other person\/group property (feature flags, cohorts, insights).\n\n\* `account` - account\n\* `person` - person\n\* `group` - group"
            ),
        group_type_index: zod
            .number()
            .min(customPropertyDefinitionsCreateBodyGroupTypeIndexMin)
            .max(customPropertyDefinitionsCreateBodyGroupTypeIndexMax)
            .nullish()
            .describe(
                "For 'group' targets only: which group type (0-4) the property attaches to. Required when target_type is 'group'; must be omitted otherwise. Create-only."
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

export const customPropertyDefinitionsUpdateBodyTargetTypeDefault = `account`
export const customPropertyDefinitionsUpdateBodyGroupTypeIndexMin = 0
export const customPropertyDefinitionsUpdateBodyGroupTypeIndexMax = 4

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
        target_type: zod
            .enum(['account', 'person', 'group'])
            .describe('\* `account` - account\n\* `person` - person\n\* `group` - group')
            .default(customPropertyDefinitionsUpdateBodyTargetTypeDefault)
            .describe(
                "What entity this property is attached to: 'account' (default), 'person', or 'group'. Person and group properties are populated from a warehouse schema and become usable like any other person\/group property (feature flags, cohorts, insights).\n\n\* `account` - account\n\* `person` - person\n\* `group` - group"
            ),
        group_type_index: zod
            .number()
            .min(customPropertyDefinitionsUpdateBodyGroupTypeIndexMin)
            .max(customPropertyDefinitionsUpdateBodyGroupTypeIndexMax)
            .nullish()
            .describe(
                "For 'group' targets only: which group type (0-4) the property attaches to. Required when target_type is 'group'; must be omitted otherwise. Create-only."
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

export const customPropertyDefinitionsPartialUpdateBodyTargetTypeDefault = `account`
export const customPropertyDefinitionsPartialUpdateBodyGroupTypeIndexMin = 0
export const customPropertyDefinitionsPartialUpdateBodyGroupTypeIndexMax = 4

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
        target_type: zod
            .enum(['account', 'person', 'group'])
            .describe('\* `account` - account\n\* `person` - person\n\* `group` - group')
            .default(customPropertyDefinitionsPartialUpdateBodyTargetTypeDefault)
            .describe(
                "What entity this property is attached to: 'account' (default), 'person', or 'group'. Person and group properties are populated from a warehouse schema and become usable like any other person\/group property (feature flags, cohorts, insights).\n\n\* `account` - account\n\* `person` - person\n\* `group` - group"
            ),
        group_type_index: zod
            .number()
            .min(customPropertyDefinitionsPartialUpdateBodyGroupTypeIndexMin)
            .max(customPropertyDefinitionsPartialUpdateBodyGroupTypeIndexMax)
            .nullish()
            .describe(
                "For 'group' targets only: which group type (0-4) the property attaches to. Required when target_type is 'group'; must be omitted otherwise. Create-only."
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
            .nullish()
            .describe(
                'UUID of the data-warehouse saved query to read from. Required for an account source. For a person or group source it must be a materialized view, and is one of the two binding options. Mutually exclusive with external_data_schema.'
            ),
        external_data_schema: zod
            .uuid()
            .nullish()
            .describe(
                'Person and group sources only: UUID of the warehouse schema (an imported table) to read from. Mutually exclusive with saved_query; a person or group source sets exactly one.'
            ),
        source_column: zod
            .string()
            .max(customPropertySourcesCreateBodySourceColumnMax)
            .nullish()
            .describe('Account sources only: column in the view whose value is written to the property.'),
        column_property_map: zod
            .unknown()
            .optional()
            .describe(
                'Person and group sources only: {warehouse_column: property_name} mapping the columns this source writes onto the person or group.'
            ),
        column_descriptions: zod
            .unknown()
            .optional()
            .describe(
                "Person and group sources only: {warehouse_column: description} giving each mapped column a human-facing description, seeded from the warehouse column's information_schema description. Optional per column. Create-only."
            ),
        key_column: zod
            .string()
            .max(customPropertySourcesCreateBodyKeyColumnMax)
            .describe(
                "Column whose value identifies the target: an account's external_id for account sources, the person's distinct_id for person sources, or the group key for group sources."
            ),
        is_enabled: zod
            .boolean()
            .default(customPropertySourcesCreateBodyIsEnabledDefault)
            .describe(
                'Whether the source syncs. Auto-disabled after repeated failures or a missing view; re-enabling resets the failure count.'
            ),
    })
    .describe(
        'Binds warehouse columns to a custom property definition. Account sources read a materialized\nview column and sync onto matching accounts; person and group sources read either an imported\nwarehouse table or a materialized view, and sync onto matching persons or groups on every\nwarehouse run of what they read.'
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

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const eventStreamsCreateBodyEnabledDefault = false
export const eventStreamsCreateBodyEventNamesItemMax = 400

export const eventStreamsCreateBodySlackChannelIdDefault = ``
export const eventStreamsCreateBodySlackChannelIdMax = 200

export const eventStreamsCreateBodySlackChannelNameDefault = ``
export const eventStreamsCreateBodySlackChannelNameMax = 200

export const EventStreamsCreateBody = /* @__PURE__ */ zod
    .object({
        enabled: zod
            .boolean()
            .default(eventStreamsCreateBodyEnabledDefault)
            .describe(
                'Whether the stream delivers to Slack. Delivery also requires at least one event, at least one member account with an external ID, and a Slack workspace + channel.'
            ),
        event_names: zod
            .array(zod.string().max(eventStreamsCreateBodyEventNamesItemMax))
            .optional()
            .describe('Names of the events to stream (matched exactly). Duplicates and blanks are dropped.'),
        slack_integration: zod
            .number()
            .nullish()
            .describe("ID of the team's Slack workspace integration to deliver through."),
        slack_channel_id: zod
            .string()
            .max(eventStreamsCreateBodySlackChannelIdMax)
            .default(eventStreamsCreateBodySlackChannelIdDefault)
            .describe('Slack channel ID to post to (e.g. C0123ABC).'),
        slack_channel_name: zod
            .string()
            .max(eventStreamsCreateBodySlackChannelNameMax)
            .default(eventStreamsCreateBodySlackChannelNameDefault)
            .describe('Display name of the Slack channel (e.g. #customer-events). Informational only.'),
    })
    .describe(
        "The caller's event stream — a live feed of selected accounts' events posted to a\nSlack channel of their choice. One stream per user per project."
    )

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const eventStreamsUpdateBodyEnabledDefault = false
export const eventStreamsUpdateBodyEventNamesItemMax = 400

export const eventStreamsUpdateBodySlackChannelIdDefault = ``
export const eventStreamsUpdateBodySlackChannelIdMax = 200

export const eventStreamsUpdateBodySlackChannelNameDefault = ``
export const eventStreamsUpdateBodySlackChannelNameMax = 200

export const EventStreamsUpdateBody = /* @__PURE__ */ zod
    .object({
        enabled: zod
            .boolean()
            .default(eventStreamsUpdateBodyEnabledDefault)
            .describe(
                'Whether the stream delivers to Slack. Delivery also requires at least one event, at least one member account with an external ID, and a Slack workspace + channel.'
            ),
        event_names: zod
            .array(zod.string().max(eventStreamsUpdateBodyEventNamesItemMax))
            .optional()
            .describe('Names of the events to stream (matched exactly). Duplicates and blanks are dropped.'),
        slack_integration: zod
            .number()
            .nullish()
            .describe("ID of the team's Slack workspace integration to deliver through."),
        slack_channel_id: zod
            .string()
            .max(eventStreamsUpdateBodySlackChannelIdMax)
            .default(eventStreamsUpdateBodySlackChannelIdDefault)
            .describe('Slack channel ID to post to (e.g. C0123ABC).'),
        slack_channel_name: zod
            .string()
            .max(eventStreamsUpdateBodySlackChannelNameMax)
            .default(eventStreamsUpdateBodySlackChannelNameDefault)
            .describe('Display name of the Slack channel (e.g. #customer-events). Informational only.'),
    })
    .describe(
        "The caller's event stream — a live feed of selected accounts' events posted to a\nSlack channel of their choice. One stream per user per project."
    )

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const eventStreamsPartialUpdateBodyEnabledDefault = false
export const eventStreamsPartialUpdateBodyEventNamesItemMax = 400

export const eventStreamsPartialUpdateBodySlackChannelIdDefault = ``
export const eventStreamsPartialUpdateBodySlackChannelIdMax = 200

export const eventStreamsPartialUpdateBodySlackChannelNameDefault = ``
export const eventStreamsPartialUpdateBodySlackChannelNameMax = 200

export const EventStreamsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        enabled: zod
            .boolean()
            .default(eventStreamsPartialUpdateBodyEnabledDefault)
            .describe(
                'Whether the stream delivers to Slack. Delivery also requires at least one event, at least one member account with an external ID, and a Slack workspace + channel.'
            ),
        event_names: zod
            .array(zod.string().max(eventStreamsPartialUpdateBodyEventNamesItemMax))
            .optional()
            .describe('Names of the events to stream (matched exactly). Duplicates and blanks are dropped.'),
        slack_integration: zod
            .number()
            .nullish()
            .describe("ID of the team's Slack workspace integration to deliver through."),
        slack_channel_id: zod
            .string()
            .max(eventStreamsPartialUpdateBodySlackChannelIdMax)
            .default(eventStreamsPartialUpdateBodySlackChannelIdDefault)
            .describe('Slack channel ID to post to (e.g. C0123ABC).'),
        slack_channel_name: zod
            .string()
            .max(eventStreamsPartialUpdateBodySlackChannelNameMax)
            .default(eventStreamsPartialUpdateBodySlackChannelNameDefault)
            .describe('Display name of the Slack channel (e.g. #customer-events). Informational only.'),
    })
    .describe(
        "The caller's event stream — a live feed of selected accounts' events posted to a\nSlack channel of their choice. One stream per user per project."
    )

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const EventStreamsAddAccountCreateBody = /* @__PURE__ */ zod
    .object({
        account_id: zod.uuid().describe('UUID of the account to add to or remove from the stream.'),
    })
    .describe('Request body for adding or removing an event-stream member account.')

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const EventStreamsRemoveAccountCreateBody = /* @__PURE__ */ zod
    .object({
        account_id: zod.uuid().describe('UUID of the account to add to or remove from the stream.'),
    })
    .describe('Request body for adding or removing an event-stream member account.')

export const featureRequestProductAreasCreateBodyNameMax = 200

export const featureRequestProductAreasCreateBodyDisplayOrderDefault = 0
export const featureRequestProductAreasCreateBodyDisplayOrderMin = 0

export const featureRequestProductAreasCreateBodyIsActiveDefault = true

export const FeatureRequestProductAreasCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(featureRequestProductAreasCreateBodyNameMax).describe('Team-maintained product area name.'),
    display_order: zod
        .number()
        .min(featureRequestProductAreasCreateBodyDisplayOrderMin)
        .default(featureRequestProductAreasCreateBodyDisplayOrderDefault)
        .describe('Position in product area selectors. Lower values appear first.'),
    is_active: zod
        .boolean()
        .default(featureRequestProductAreasCreateBodyIsActiveDefault)
        .describe('Whether editors can select this product area for new requests.'),
})

export const featureRequestProductAreasUpdateBodyNameMax = 200

export const featureRequestProductAreasUpdateBodyDisplayOrderDefault = 0
export const featureRequestProductAreasUpdateBodyDisplayOrderMin = 0

export const featureRequestProductAreasUpdateBodyIsActiveDefault = true

export const FeatureRequestProductAreasUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(featureRequestProductAreasUpdateBodyNameMax).describe('Team-maintained product area name.'),
    display_order: zod
        .number()
        .min(featureRequestProductAreasUpdateBodyDisplayOrderMin)
        .default(featureRequestProductAreasUpdateBodyDisplayOrderDefault)
        .describe('Position in product area selectors. Lower values appear first.'),
    is_active: zod
        .boolean()
        .default(featureRequestProductAreasUpdateBodyIsActiveDefault)
        .describe('Whether editors can select this product area for new requests.'),
})

export const featureRequestProductAreasPartialUpdateBodyNameMax = 200

export const featureRequestProductAreasPartialUpdateBodyDisplayOrderDefault = 0
export const featureRequestProductAreasPartialUpdateBodyDisplayOrderMin = 0

export const featureRequestProductAreasPartialUpdateBodyIsActiveDefault = true

export const FeatureRequestProductAreasPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(featureRequestProductAreasPartialUpdateBodyNameMax)
        .optional()
        .describe('Team-maintained product area name.'),
    display_order: zod
        .number()
        .min(featureRequestProductAreasPartialUpdateBodyDisplayOrderMin)
        .default(featureRequestProductAreasPartialUpdateBodyDisplayOrderDefault)
        .describe('Position in product area selectors. Lower values appear first.'),
    is_active: zod
        .boolean()
        .default(featureRequestProductAreasPartialUpdateBodyIsActiveDefault)
        .describe('Whether editors can select this product area for new requests.'),
})

export const featureRequestsCreateBodyTitleMax = 400

export const featureRequestsCreateBodyDescriptionDefault = ``
export const featureRequestsCreateBodyEvidenceOneSummaryDefault = ``
export const featureRequestsCreateBodyEvidenceOneCustomerQuoteDefault = ``
export const featureRequestsCreateBodyEvidenceOneEvidenceSourceMax = 200

export const featureRequestsCreateBodyEvidenceOneSourceUrlDefault = ``
export const featureRequestsCreateBodyEvidenceOneSourceUrlMax = 2000

export const FeatureRequestsCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(featureRequestsCreateBodyTitleMax).describe('Required customer-facing request title.'),
    description: zod
        .string()
        .default(featureRequestsCreateBodyDescriptionDefault)
        .describe('Optional customer-facing request description in Markdown.'),
    account_id: zod.uuid().describe('ID of the affected Customer Analytics account.'),
    product_area_ids: zod.array(zod.uuid()).describe('One or more active product area IDs. Duplicate IDs are ignored.'),
    idempotency_key: zod
        .uuid()
        .describe(
            'Client-generated key that makes retries return the original request instead of creating a duplicate.'
        ),
    evidence: zod
        .union([
            zod.object({
                summary: zod
                    .string()
                    .default(featureRequestsCreateBodyEvidenceOneSummaryDefault)
                    .describe("Internal summary of this account's request evidence."),
                customer_quote: zod
                    .string()
                    .default(featureRequestsCreateBodyEvidenceOneCustomerQuoteDefault)
                    .describe('Customer quote kept with this evidence item.'),
                evidence_source: zod
                    .string()
                    .max(featureRequestsCreateBodyEvidenceOneEvidenceSourceMax)
                    .describe('Free-form name of the source where this evidence was recorded.'),
                source_url: zod
                    .url()
                    .max(featureRequestsCreateBodyEvidenceOneSourceUrlMax)
                    .default(featureRequestsCreateBodyEvidenceOneSourceUrlDefault)
                    .describe('Optional HTTP or HTTPS link to the source.'),
                requested_on: zod.iso
                    .date()
                    .nullish()
                    .describe('Date the account made the request, or null when unknown.'),
                image_ids: zod
                    .array(zod.uuid())
                    .optional()
                    .describe('Uploaded image IDs from this project to attach in display order.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('Optional first evidence item to create for the selected account.'),
})

export const featureRequestsUpdateBodyTitleMax = 400

export const FeatureRequestsUpdateBody = /* @__PURE__ */ zod.object({
    expected_version: zod
        .number()
        .min(1)
        .describe('Request version loaded by the editor. Stale versions return 409 Conflict.'),
    title: zod
        .string()
        .max(featureRequestsUpdateBodyTitleMax)
        .optional()
        .describe('Updated customer-facing request title.'),
    description: zod.string().optional().describe('Updated optional customer-facing request description in Markdown.'),
    account_id: zod.uuid().optional().describe('Deprecated single affected account ID. Use account_ids.'),
    account_ids: zod
        .array(zod.uuid())
        .optional()
        .describe('One or more affected account IDs. Removed accounts are unlinked without deleting their evidence.'),
    product_area_ids: zod
        .array(zod.uuid())
        .optional()
        .describe('One or more product area IDs. Existing inactive areas can remain linked.'),
    request_status: zod
        .enum(['requested', 'planned', 'completed', 'wont_fix', 'duplicate'])
        .describe(
            "\* `requested` - Requested\n\* `planned` - Planned\n\* `completed` - Completed\n\* `wont_fix` - Won't fix\n\* `duplicate` - Duplicate"
        )
        .optional()
        .describe(
            "Updated customer-facing lifecycle status.\n\n\* `requested` - Requested\n\* `planned` - Planned\n\* `completed` - Completed\n\* `wont_fix` - Won't fix\n\* `duplicate` - Duplicate"
        ),
    request_priority: zod
        .union([
            zod.enum(['high', 'medium', 'low']).describe('\* `high` - High\n\* `medium` - Medium\n\* `low` - Low'),
            zod.null(),
        ])
        .optional()
        .describe(
            'Updated manual priority. Pass null to remove the priority.\n\n\* `high` - High\n\* `medium` - Medium\n\* `low` - Low'
        ),
})

export const featureRequestsPartialUpdateBodyTitleMax = 400

export const FeatureRequestsPartialUpdateBody = /* @__PURE__ */ zod.object({
    expected_version: zod
        .number()
        .min(1)
        .optional()
        .describe('Request version loaded by the editor. Stale versions return 409 Conflict.'),
    title: zod
        .string()
        .max(featureRequestsPartialUpdateBodyTitleMax)
        .optional()
        .describe('Updated customer-facing request title.'),
    description: zod.string().optional().describe('Updated optional customer-facing request description in Markdown.'),
    account_id: zod.uuid().optional().describe('Deprecated single affected account ID. Use account_ids.'),
    account_ids: zod
        .array(zod.uuid())
        .optional()
        .describe('One or more affected account IDs. Removed accounts are unlinked without deleting their evidence.'),
    product_area_ids: zod
        .array(zod.uuid())
        .optional()
        .describe('One or more product area IDs. Existing inactive areas can remain linked.'),
    request_status: zod
        .enum(['requested', 'planned', 'completed', 'wont_fix', 'duplicate'])
        .describe(
            "\* `requested` - Requested\n\* `planned` - Planned\n\* `completed` - Completed\n\* `wont_fix` - Won't fix\n\* `duplicate` - Duplicate"
        )
        .optional()
        .describe(
            "Updated customer-facing lifecycle status.\n\n\* `requested` - Requested\n\* `planned` - Planned\n\* `completed` - Completed\n\* `wont_fix` - Won't fix\n\* `duplicate` - Duplicate"
        ),
    request_priority: zod
        .union([
            zod.enum(['high', 'medium', 'low']).describe('\* `high` - High\n\* `medium` - Medium\n\* `low` - Low'),
            zod.null(),
        ])
        .optional()
        .describe(
            'Updated manual priority. Pass null to remove the priority.\n\n\* `high` - High\n\* `medium` - Medium\n\* `low` - Low'
        ),
})

export const featureRequestsAddAccountCreateBodyEvidenceOneSummaryDefault = ``
export const featureRequestsAddAccountCreateBodyEvidenceOneCustomerQuoteDefault = ``
export const featureRequestsAddAccountCreateBodyEvidenceOneEvidenceSourceMax = 200

export const featureRequestsAddAccountCreateBodyEvidenceOneSourceUrlDefault = ``
export const featureRequestsAddAccountCreateBodyEvidenceOneSourceUrlMax = 2000

export const FeatureRequestsAddAccountCreateBody = /* @__PURE__ */ zod.object({
    expected_version: zod
        .number()
        .min(1)
        .describe('Request version loaded by the editor. Stale versions return 409 Conflict.'),
    account_id: zod.uuid().describe('Accessible account to link to this feature request.'),
    evidence: zod
        .union([
            zod.object({
                summary: zod
                    .string()
                    .default(featureRequestsAddAccountCreateBodyEvidenceOneSummaryDefault)
                    .describe("Internal summary of this account's request evidence."),
                customer_quote: zod
                    .string()
                    .default(featureRequestsAddAccountCreateBodyEvidenceOneCustomerQuoteDefault)
                    .describe('Customer quote kept with this evidence item.'),
                evidence_source: zod
                    .string()
                    .max(featureRequestsAddAccountCreateBodyEvidenceOneEvidenceSourceMax)
                    .describe('Free-form name of the source where this evidence was recorded.'),
                source_url: zod
                    .url()
                    .max(featureRequestsAddAccountCreateBodyEvidenceOneSourceUrlMax)
                    .default(featureRequestsAddAccountCreateBodyEvidenceOneSourceUrlDefault)
                    .describe('Optional HTTP or HTTPS link to the source.'),
                requested_on: zod.iso
                    .date()
                    .nullish()
                    .describe('Date the account made the request, or null when unknown.'),
                image_ids: zod
                    .array(zod.uuid())
                    .optional()
                    .describe('Uploaded image IDs from this project to attach in display order.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('Optional first evidence item to create for the account in the same change.'),
})

export const featureRequestsAddEvidenceCreateBodySummaryDefault = ``
export const featureRequestsAddEvidenceCreateBodyCustomerQuoteDefault = ``
export const featureRequestsAddEvidenceCreateBodyEvidenceSourceMax = 200

export const featureRequestsAddEvidenceCreateBodySourceUrlDefault = ``
export const featureRequestsAddEvidenceCreateBodySourceUrlMax = 2000

export const FeatureRequestsAddEvidenceCreateBody = /* @__PURE__ */ zod.object({
    summary: zod
        .string()
        .default(featureRequestsAddEvidenceCreateBodySummaryDefault)
        .describe("Internal summary of this account's request evidence."),
    customer_quote: zod
        .string()
        .default(featureRequestsAddEvidenceCreateBodyCustomerQuoteDefault)
        .describe('Customer quote kept with this evidence item.'),
    evidence_source: zod
        .string()
        .max(featureRequestsAddEvidenceCreateBodyEvidenceSourceMax)
        .describe('Free-form name of the source where this evidence was recorded.'),
    source_url: zod
        .url()
        .max(featureRequestsAddEvidenceCreateBodySourceUrlMax)
        .default(featureRequestsAddEvidenceCreateBodySourceUrlDefault)
        .describe('Optional HTTP or HTTPS link to the source.'),
    requested_on: zod.iso.date().nullish().describe('Date the account made the request, or null when unknown.'),
    image_ids: zod
        .array(zod.uuid())
        .optional()
        .describe('Uploaded image IDs from this project to attach in display order.'),
    expected_version: zod
        .number()
        .min(1)
        .describe('Request version loaded by the editor. Stale versions return 409 Conflict.'),
    account_link_id: zod.uuid().describe('Active account link that owns this evidence.'),
})

export const FeatureRequestsArchiveCreateBody = /* @__PURE__ */ zod.object({
    expected_version: zod
        .number()
        .min(1)
        .describe('Request version loaded by the editor. Stale versions return 409 Conflict.'),
})

export const FeatureRequestsRemoveEvidenceCreateBody = /* @__PURE__ */ zod.object({
    expected_version: zod
        .number()
        .min(1)
        .describe('Request version loaded by the editor. Stale versions return 409 Conflict.'),
    evidence_id: zod.uuid().describe('Evidence item to delete.'),
})

export const FeatureRequestsRestoreCreateBody = /* @__PURE__ */ zod.object({
    expected_version: zod
        .number()
        .min(1)
        .describe('Request version loaded by the editor. Stale versions return 409 Conflict.'),
})

export const featureRequestsUpdateEvidenceCreateBodySummaryDefault = ``
export const featureRequestsUpdateEvidenceCreateBodyCustomerQuoteDefault = ``
export const featureRequestsUpdateEvidenceCreateBodyEvidenceSourceMax = 200

export const featureRequestsUpdateEvidenceCreateBodySourceUrlDefault = ``
export const featureRequestsUpdateEvidenceCreateBodySourceUrlMax = 2000

export const FeatureRequestsUpdateEvidenceCreateBody = /* @__PURE__ */ zod.object({
    summary: zod
        .string()
        .default(featureRequestsUpdateEvidenceCreateBodySummaryDefault)
        .describe("Internal summary of this account's request evidence."),
    customer_quote: zod
        .string()
        .default(featureRequestsUpdateEvidenceCreateBodyCustomerQuoteDefault)
        .describe('Customer quote kept with this evidence item.'),
    evidence_source: zod
        .string()
        .max(featureRequestsUpdateEvidenceCreateBodyEvidenceSourceMax)
        .describe('Free-form name of the source where this evidence was recorded.'),
    source_url: zod
        .url()
        .max(featureRequestsUpdateEvidenceCreateBodySourceUrlMax)
        .default(featureRequestsUpdateEvidenceCreateBodySourceUrlDefault)
        .describe('Optional HTTP or HTTPS link to the source.'),
    requested_on: zod.iso.date().nullish().describe('Date the account made the request, or null when unknown.'),
    image_ids: zod
        .array(zod.uuid())
        .optional()
        .describe('Uploaded image IDs from this project to attach in display order.'),
    expected_version: zod
        .number()
        .min(1)
        .describe('Request version loaded by the editor. Stale versions return 409 Conflict.'),
    evidence_id: zod.uuid().describe('Evidence item to replace.'),
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
