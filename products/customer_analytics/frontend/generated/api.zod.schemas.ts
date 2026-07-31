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

export const ExternalAccountListAssignmentApi = zod.object({
    user_id: zod.number().describe('PostHog user id of the assigned user.'),
    email: zod.string().describe('Current email address of the assigned user.'),
    name: zod
        .string()
        .nullable()
        .describe('Current display name of the assigned user, or null when the user has no name set.'),
})

export type ExternalAccountListAssignmentApi = zod.input<typeof ExternalAccountListAssignmentApi>
export type ExternalAccountListAssignmentApiOutput = zod.output<typeof ExternalAccountListAssignmentApi>

export const ExternalAccountListItemApi = zod.object({
    external_id: zod.string().describe('External account key used by downstream systems.'),
    name: zod.string().describe('Human-readable account name.'),
    relationships: zod
        .record(zod.string(), zod.array(ExternalAccountListAssignmentApi))
        .describe(
            "Active relationship assignments to current organization members, keyed by relationship definition name (e.g. 'CSM', 'Account executive'). Definitions with no active assignment are omitted."
        ),
})

export type ExternalAccountListItemApi = zod.input<typeof ExternalAccountListItemApi>
export type ExternalAccountListItemApiOutput = zod.output<typeof ExternalAccountListItemApi>

export const ExternalAccountListPageApi = zod.object({
    results: zod.array(ExternalAccountListItemApi).describe('Accounts in this page, ordered by account id.'),
    next_cursor: zod
        .string()
        .nullable()
        .describe('Account UUID to pass as `cursor` for the next page, or null when the list is exhausted.'),
})

export type ExternalAccountListPageApi = zod.input<typeof ExternalAccountListPageApi>
export type ExternalAccountListPageApiOutput = zod.output<typeof ExternalAccountListPageApi>

export const ExternalAccountListValidationErrorApi = zod.object({
    error: zod.record(zod.string(), zod.array(zod.string())).describe('Validation errors keyed by query parameter.'),
})

export type ExternalAccountListValidationErrorApi = zod.input<typeof ExternalAccountListValidationErrorApi>
export type ExternalAccountListValidationErrorApiOutput = zod.output<typeof ExternalAccountListValidationErrorApi>

export const ErrorResponseApi = zod.object({
    error: zod.string().describe('Error message'),
})

export type ErrorResponseApi = zod.input<typeof ErrorResponseApi>
export type ErrorResponseApiOutput = zod.output<typeof ErrorResponseApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const AccountNoteApi = zod
    .object({
        short_id: zod.string().describe('URL-safe short ID of the notebook.'),
        title: zod.string().nullable().describe('Title of the note.'),
        created_at: zod.iso.datetime({ offset: true }).describe('When the note was created.'),
        last_modified_at: zod.iso.datetime({ offset: true }).describe('When the note was last modified.'),
        account_id: zod.uuid().describe('UUID of the account this note is linked to.'),
        account_name: zod.string().describe('Name of the account this note is linked to.'),
        created_by: zod.union([UserBasicApi, zod.null()]).describe('User who created the note, if known.'),
    })
    .describe('A team-wide account note — an internal notebook linked to a Customer analytics account.')

export type AccountNoteApi = zod.input<typeof AccountNoteApi>
export type AccountNoteApiOutput = zod.output<typeof AccountNoteApi>

export const PaginatedAccountNoteListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(AccountNoteApi),
})

export type PaginatedAccountNoteListApi = zod.input<typeof PaginatedAccountNoteListApi>
export type PaginatedAccountNoteListApiOutput = zod.output<typeof PaginatedAccountNoteListApi>

export const accountRelationshipDefinitionApiNameMax = 400

export const accountRelationshipDefinitionApiIsSingleHolderDefault = true

export const AccountRelationshipDefinitionApi = zod
    .object({
        id: zod.uuid().describe('Relationship definition UUID.'),
        name: zod
            .string()
            .max(accountRelationshipDefinitionApiNameMax)
            .describe('Human-readable name of the relationship. Unique within the team.'),
        description: zod
            .string()
            .nullish()
            .describe(
                "What this relationship means, e.g. 'The customer success manager responsible for this account'."
            ),
        is_single_holder: zod
            .boolean()
            .default(accountRelationshipDefinitionApiIsSingleHolderDefault)
            .describe(
                'Whether only one user can hold this relationship per account at a time, e.g. a single CSM per account.'
            ),
    })
    .describe('A team-defined account relationship type (CSM, Onboarding manager, ...).')

export type AccountRelationshipDefinitionApi = zod.input<typeof AccountRelationshipDefinitionApi>
export type AccountRelationshipDefinitionApiOutput = zod.output<typeof AccountRelationshipDefinitionApi>

export const PaginatedAccountRelationshipDefinitionListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(AccountRelationshipDefinitionApi),
})

export type PaginatedAccountRelationshipDefinitionListApi = zod.input<
    typeof PaginatedAccountRelationshipDefinitionListApi
>
export type PaginatedAccountRelationshipDefinitionListApiOutput = zod.output<
    typeof PaginatedAccountRelationshipDefinitionListApi
>

export const patchedAccountRelationshipDefinitionApiNameMax = 400

export const patchedAccountRelationshipDefinitionApiIsSingleHolderDefault = true

export const PatchedAccountRelationshipDefinitionApi = zod
    .object({
        id: zod.uuid().optional().describe('Relationship definition UUID.'),
        name: zod
            .string()
            .max(patchedAccountRelationshipDefinitionApiNameMax)
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
            .default(patchedAccountRelationshipDefinitionApiIsSingleHolderDefault)
            .describe(
                'Whether only one user can hold this relationship per account at a time, e.g. a single CSM per account.'
            ),
    })
    .describe('A team-defined account relationship type (CSM, Onboarding manager, ...).')

export type PatchedAccountRelationshipDefinitionApi = zod.input<typeof PatchedAccountRelationshipDefinitionApi>
export type PatchedAccountRelationshipDefinitionApiOutput = zod.output<typeof PatchedAccountRelationshipDefinitionApi>

export const SlackSummaryCadenceEnumApi = zod
    .enum(['daily', 'weekly', 'monthly'])
    .describe('\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly')

export type SlackSummaryCadenceEnumApi = zod.input<typeof SlackSummaryCadenceEnumApi>
export type SlackSummaryCadenceEnumApiOutput = zod.output<typeof SlackSummaryCadenceEnumApi>

export const accountApiNameMax = 400

export const accountApiExternalIdMax = 400

export const AccountApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(accountApiNameMax).describe('Human-readable name of the account.'),
        external_id: zod
            .string()
            .max(accountApiExternalIdMax)
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
        notebooks: zod
            .array(zod.string())
            .describe(
                'Short IDs of the internal notebooks linked to this account, used to persist investigations, call notes, and other free-form context. Empty list if no notebooks have been created for the account.'
            ),
        slack_summary_cadence: zod
            .union([SlackSummaryCadenceEnumApi, zod.null()])
            .optional()
            .describe(
                "How often to generate an AI summary of the account's bound Slack channel (daily, weekly, or monthly). Null means summaries are off.\n\n\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly"
            ),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: zod.number().nullable(),
        updated_at: zod.iso.datetime({ offset: true }).nullable(),
    })
    .describe('A Customer Analytics account — a logical grouping used to assign customer-success ownership.')

export type AccountApi = zod.input<typeof AccountApi>
export type AccountApiOutput = zod.output<typeof AccountApi>

export const PaginatedAccountListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(AccountApi),
})

export type PaginatedAccountListApi = zod.input<typeof PaginatedAccountListApi>
export type PaginatedAccountListApiOutput = zod.output<typeof PaginatedAccountListApi>

export const CustomPropertyValueApi = zod
    .object({
        id: zod.uuid().describe('Unique id of this value record.'),
        account_id: zod.uuid().describe('Account the value belongs to.'),
        definition_id: zod.uuid().describe('Custom property definition the value is for.'),
        value: zod
            .union([zod.string(), zod.number(), zod.boolean()])
            .describe("The stored value, typed per the property's data type."),
        created_at: zod.iso.datetime({ offset: true }).describe('When this value was set.'),
        created_by_id: zod.number().nullable().describe('Id of the user who set this value, if known.'),
    })
    .describe("An account's current value for a custom property (read shape).")

export type CustomPropertyValueApi = zod.input<typeof CustomPropertyValueApi>
export type CustomPropertyValueApiOutput = zod.output<typeof CustomPropertyValueApi>

export const CustomPropertyValueWriteApi = zod.object({
    definition: zod.uuid().describe('UUID of the custom property definition whose value to set for this account.'),
    value: zod
        .union([zod.string(), zod.number(), zod.boolean()])
        .describe(
            "Value to store, matching the definition's type: a number for number\/currency\/percent, a boolean for boolean, an ISO-8601 string for date\/datetime, or text for text properties."
        ),
})

export type CustomPropertyValueWriteApi = zod.input<typeof CustomPropertyValueWriteApi>
export type CustomPropertyValueWriteApiOutput = zod.output<typeof CustomPropertyValueWriteApi>

export const accountNotebookApiTitleMax = 256

export const AccountNotebookApi = zod.object({
    id: zod.uuid(),
    short_id: zod.string(),
    title: zod
        .string()
        .max(accountNotebookApiTitleMax)
        .nullish()
        .describe('Human-readable title of the account notebook.'),
    content: zod.unknown().optional().describe('Notebook content as a ProseMirror JSON document structure.'),
    text_content: zod.string().nullish().describe('Plain text representation of the notebook content for search.'),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    last_modified_at: zod.iso.datetime({ offset: true }),
    last_modified_by: UserBasicApi,
})

export type AccountNotebookApi = zod.input<typeof AccountNotebookApi>
export type AccountNotebookApiOutput = zod.output<typeof AccountNotebookApi>

export const PaginatedAccountNotebookListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(AccountNotebookApi),
})

export type PaginatedAccountNotebookListApi = zod.input<typeof PaginatedAccountNotebookListApi>
export type PaginatedAccountNotebookListApiOutput = zod.output<typeof PaginatedAccountNotebookListApi>

export const AccountAssignmentApi = zod
    .object({
        id: zod.number().describe('PostHog user id of the assignee.'),
        email: zod.email().describe('Email of the assignee.'),
    })
    .describe('A user assigned to an account relationship (read shape).')

export type AccountAssignmentApi = zod.input<typeof AccountAssignmentApi>
export type AccountAssignmentApiOutput = zod.output<typeof AccountAssignmentApi>

export const AccountRelationshipApi = zod
    .object({
        id: zod.uuid().describe('Unique id of this assignment row.'),
        definition: AccountRelationshipDefinitionApi.describe('The relationship type this assignment belongs to.'),
        user: zod
            .union([AccountAssignmentApi, zod.null()])
            .describe('The assigned user; null when their account was deleted.'),
        started_at: zod.iso.datetime({ offset: true }).describe('When this assignment became effective.'),
        ended_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('When this assignment ended; null while it is active.'),
    })
    .describe('One assignment of a user to an account relationship, with its effective range.')

export type AccountRelationshipApi = zod.input<typeof AccountRelationshipApi>
export type AccountRelationshipApiOutput = zod.output<typeof AccountRelationshipApi>

export const AccountRelationshipWriteApi = zod
    .object({
        definition: zod.uuid().describe('Id of the relationship definition to assign.'),
        user: zod.number().describe("PostHog user id of the assignee. Must be a member of the account's organization."),
    })
    .describe('Input for assigning a user to an account relationship.')

export type AccountRelationshipWriteApi = zod.input<typeof AccountRelationshipWriteApi>
export type AccountRelationshipWriteApiOutput = zod.output<typeof AccountRelationshipWriteApi>

export const patchedAccountApiNameMax = 400

export const patchedAccountApiExternalIdMax = 400

export const PatchedAccountApi = zod
    .object({
        id: zod.uuid().optional(),
        name: zod.string().max(patchedAccountApiNameMax).optional().describe('Human-readable name of the account.'),
        external_id: zod
            .string()
            .max(patchedAccountApiExternalIdMax)
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
        notebooks: zod
            .array(zod.string())
            .optional()
            .describe(
                'Short IDs of the internal notebooks linked to this account, used to persist investigations, call notes, and other free-form context. Empty list if no notebooks have been created for the account.'
            ),
        slack_summary_cadence: zod
            .union([SlackSummaryCadenceEnumApi, zod.null()])
            .optional()
            .describe(
                "How often to generate an AI summary of the account's bound Slack channel (daily, weekly, or monthly). Null means summaries are off.\n\n\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly"
            ),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        created_by: zod.number().nullish(),
        updated_at: zod.iso.datetime({ offset: true }).nullish(),
    })
    .describe('A Customer Analytics account — a logical grouping used to assign customer-success ownership.')

export type PatchedAccountApi = zod.input<typeof PatchedAccountApi>
export type PatchedAccountApiOutput = zod.output<typeof PatchedAccountApi>

export const ChannelSummaryMessageApi = zod
    .object({
        author: zod.string().describe('Display name of the message author.'),
        sent_at: zod.iso.datetime({ offset: true }).describe('When the message was sent.'),
        permalink: zod.string().describe('Slack permalink to the message.'),
    })
    .describe('Metadata for one message a channel summary covered — never the message text.')

export type ChannelSummaryMessageApi = zod.input<typeof ChannelSummaryMessageApi>
export type ChannelSummaryMessageApiOutput = zod.output<typeof ChannelSummaryMessageApi>

export const AccountChannelSummaryApi = zod
    .object({
        id: zod.uuid().describe('UUID of the summary.'),
        slack_channel_id: zod
            .string()
            .describe('Slack channel the summary covered — kept even if the account is later rebound.'),
        cadence: SlackSummaryCadenceEnumApi.describe(
            'Cadence the summarized period belongs to (daily, weekly, or monthly).\n\n\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly'
        ),
        period_start: zod.iso.datetime({ offset: true }).describe('Start of the summarized period (inclusive).'),
        period_end: zod.iso.datetime({ offset: true }).describe('End of the summarized period (exclusive).'),
        content: zod.string().describe('Markdown summary citing the original Slack messages with permalinks.'),
        message_count: zod.number().describe('Number of channel messages the summary covered.'),
        messages: zod
            .array(ChannelSummaryMessageApi)
            .describe('The messages the summary covered, in transcript order — metadata only, no message text.'),
        generated_at: zod.iso.datetime({ offset: true }).describe('When the summary was generated.'),
    })
    .describe("An AI summary of one closed period of the account's bound Slack channel (read-only).")

export type AccountChannelSummaryApi = zod.input<typeof AccountChannelSummaryApi>
export type AccountChannelSummaryApiOutput = zod.output<typeof AccountChannelSummaryApi>

export const PaginatedAccountChannelSummaryListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(AccountChannelSummaryApi),
})

export type PaginatedAccountChannelSummaryListApi = zod.input<typeof PaginatedAccountChannelSummaryListApi>
export type PaginatedAccountChannelSummaryListApiOutput = zod.output<typeof PaginatedAccountChannelSummaryListApi>

export const SupportTicketApi = zod
    .object({
        id: zod.string().describe('UUID of the support ticket.'),
        ticket_number: zod.number().describe('Human-readable ticket number.'),
        status: zod.string().describe("Current status of the ticket (e.g. 'new', 'open')."),
        last_message_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('When the most recent message was sent on this ticket.'),
        last_message_text: zod.string().nullable().describe('Truncated preview of the most recent message.'),
        deep_link: zod.string().describe('Absolute URL to open this ticket in the app.'),
    })
    .describe('A support ticket linked to an account, sourced from the conversations product (read-only).')

export type SupportTicketApi = zod.input<typeof SupportTicketApi>
export type SupportTicketApiOutput = zod.output<typeof SupportTicketApi>

export const AnnouncementStatusEnumApi = zod
    .enum(['pending', 'sending', 'sent', 'partially_failed', 'failed'])
    .describe(
        '\* `pending` - Pending\n\* `sending` - Sending\n\* `sent` - Sent\n\* `partially_failed` - Partially failed\n\* `failed` - Failed'
    )

export type AnnouncementStatusEnumApi = zod.input<typeof AnnouncementStatusEnumApi>
export type AnnouncementStatusEnumApiOutput = zod.output<typeof AnnouncementStatusEnumApi>

export const AnnouncementDeliveryStatusEnumApi = zod
    .enum(['pending', 'sent', 'failed'])
    .describe('\* `pending` - Pending\n\* `sent` - Sent\n\* `failed` - Failed')

export type AnnouncementDeliveryStatusEnumApi = zod.input<typeof AnnouncementDeliveryStatusEnumApi>
export type AnnouncementDeliveryStatusEnumApiOutput = zod.output<typeof AnnouncementDeliveryStatusEnumApi>

export const AnnouncementDeliveryApi = zod.object({
    id: zod.uuid(),
    slack_channel_id: zod.string().describe('Slack channel ID the message was sent to (e.g. C0123ABCD).'),
    slack_channel_name: zod.string().describe('Slack channel display name at send time (without the leading #).'),
    status: AnnouncementDeliveryStatusEnumApi.describe(
        'Per-channel delivery status: pending, sent, or failed.\n\n\* `pending` - Pending\n\* `sent` - Sent\n\* `failed` - Failed'
    ),
    error: zod.string().describe('Slack error code when delivery to this channel failed; empty otherwise.'),
    slack_message_ts: zod.string().describe('Timestamp ID of the posted Slack message, when delivery succeeded.'),
    sent_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the message was delivered to this channel. Null until sent.'),
})

export type AnnouncementDeliveryApi = zod.input<typeof AnnouncementDeliveryApi>
export type AnnouncementDeliveryApiOutput = zod.output<typeof AnnouncementDeliveryApi>

export const AnnouncementApi = zod.object({
    id: zod.uuid(),
    short_id: zod.string().describe('Short human-friendly identifier for the announcement.'),
    message: zod.string().describe('Message body to send, rendered as Slack mrkdwn.'),
    status: AnnouncementStatusEnumApi.describe(
        'Overall status: pending, sending, sent, partially_failed, or failed.\n\n\* `pending` - Pending\n\* `sending` - Sending\n\* `sent` - Sent\n\* `partially_failed` - Partially failed\n\* `failed` - Failed'
    ),
    total_channels: zod.number().describe('Number of channels this announcement targets.'),
    sent_count: zod.number().describe('Number of channels the message was successfully delivered to.'),
    failed_count: zod.number().describe('Number of channels delivery failed for.'),
    sent_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When delivery finished (all channels resolved). Null while pending\/sending.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When the announcement was created.'),
    created_by: UserBasicApi,
    deliveries: zod
        .array(AnnouncementDeliveryApi)
        .describe('Per-channel delivery rows, one per selected Slack channel.'),
    channels: zod
        .array(zod.string())
        .describe(
            'Slack channel IDs to send to. Each must be a channel the SupportHog bot is a member of; names are resolved server-side.'
        ),
})

export type AnnouncementApi = zod.input<typeof AnnouncementApi>
export type AnnouncementApiOutput = zod.output<typeof AnnouncementApi>

export const PaginatedAnnouncementListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(AnnouncementApi),
})

export type PaginatedAnnouncementListApi = zod.input<typeof PaginatedAnnouncementListApi>
export type PaginatedAnnouncementListApiOutput = zod.output<typeof PaginatedAnnouncementListApi>

export const AnnouncementChannelApi = zod.object({
    id: zod.string().describe('Slack channel ID (e.g. C0123ABCD).'),
    name: zod.string().describe('Slack channel display name (without the leading #).'),
    is_member: zod.boolean().describe('Whether the SupportHog bot is a member of this channel.'),
    customer_name: zod
        .string()
        .nullable()
        .describe('Name of the customer account whose slack_channel_id points at this channel, or null if unmapped.'),
})

export type AnnouncementChannelApi = zod.input<typeof AnnouncementChannelApi>
export type AnnouncementChannelApiOutput = zod.output<typeof AnnouncementChannelApi>

export const CustomPropertyDisplayTypeEnumApi = zod
    .enum(['text', 'number', 'currency', 'percent', 'date', 'datetime', 'boolean', 'select'])
    .describe(
        '\* `text` - text\n\* `number` - number\n\* `currency` - currency\n\* `percent` - percent\n\* `date` - date\n\* `datetime` - datetime\n\* `boolean` - boolean\n\* `select` - select'
    )

export type CustomPropertyDisplayTypeEnumApi = zod.input<typeof CustomPropertyDisplayTypeEnumApi>
export type CustomPropertyDisplayTypeEnumApiOutput = zod.output<typeof CustomPropertyDisplayTypeEnumApi>

export const CustomPropertyDefinitionTargetTypeEnumApi = zod
    .enum(['account', 'person', 'group'])
    .describe('\* `account` - account\n\* `person` - person\n\* `group` - group')

export type CustomPropertyDefinitionTargetTypeEnumApi = zod.input<typeof CustomPropertyDefinitionTargetTypeEnumApi>
export type CustomPropertyDefinitionTargetTypeEnumApiOutput = zod.output<
    typeof CustomPropertyDefinitionTargetTypeEnumApi
>

export const CustomPropertyOptionColorEnumApi = zod
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

export type CustomPropertyOptionColorEnumApi = zod.input<typeof CustomPropertyOptionColorEnumApi>
export type CustomPropertyOptionColorEnumApiOutput = zod.output<typeof CustomPropertyOptionColorEnumApi>

export const customPropertyOptionApiLabelMax = 400

export const CustomPropertyOptionApi = zod
    .object({
        id: zod
            .string()
            .nullish()
            .describe(
                'Server-assigned stable id of the option. Omit for new options; send it back unchanged when editing so renames and removals can be told apart.'
            ),
        label: zod
            .string()
            .max(customPropertyOptionApiLabelMax)
            .describe("Display label of the option. Stored as the account's value when picked."),
        color: CustomPropertyOptionColorEnumApi.describe(
            "Preset color token used to render the option ('preset-1' through 'preset-10').\n\n\* `preset-1` - preset-1\n\* `preset-2` - preset-2\n\* `preset-3` - preset-3\n\* `preset-4` - preset-4\n\* `preset-5` - preset-5\n\* `preset-6` - preset-6\n\* `preset-7` - preset-7\n\* `preset-8` - preset-8\n\* `preset-9` - preset-9\n\* `preset-10` - preset-10"
        ),
    })
    .describe('An allowed value of a select custom property.')

export type CustomPropertyOptionApi = zod.input<typeof CustomPropertyOptionApi>
export type CustomPropertyOptionApiOutput = zod.output<typeof CustomPropertyOptionApi>

export const CustomPropertySyncRunApi = zod
    .object({
        id: zod.uuid(),
        trigger: zod
            .string()
            .describe("What started the run: 'scheduled' (rode a warehouse sync), 'manual', or 'backfill'."),
        status: zod.string().describe("Run status: 'running', 'completed', or 'failed'."),
        started_at: zod.iso.datetime({ offset: true }).nullable().describe('When the run began.'),
        finished_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('When the run ended, or null while running.'),
        rows_read: zod.number().describe('Warehouse rows scanned this run.'),
        changed: zod.number().describe('Rows whose mapped values changed since the last run.'),
        existing: zod
            .number()
            .describe('Person or group profiles updated (changed rows that matched an existing person\/group).'),
        produced: zod.number().describe('Property-update intents produced to the ingestion pipeline.'),
        skipped_missing_person: zod
            .number()
            .describe('Changed rows dropped because no existing person\/group matched the key column value.'),
        error: zod.string().nullable().describe('Error summary if the run failed, else null.'),
        created_at: zod.iso.datetime({ offset: true }).describe('When the run row was recorded.'),
    })
    .describe(
        'One person- or group-property sync or backfill run. Read-only: runs are created by the\nsync\/backfill pipeline, never through the API.'
    )

export type CustomPropertySyncRunApi = zod.input<typeof CustomPropertySyncRunApi>
export type CustomPropertySyncRunApiOutput = zod.output<typeof CustomPropertySyncRunApi>

export const customPropertySourceApiSourceColumnMax = 400

export const customPropertySourceApiKeyColumnMax = 400

export const customPropertySourceApiIsEnabledDefault = true

export const CustomPropertySourceApi = zod
    .object({
        id: zod.uuid(),
        definition: zod
            .uuid()
            .describe('UUID of the custom property definition this source feeds. One source per definition.'),
        saved_query: zod
            .uuid()
            .nullish()
            .describe(
                'Account sources only: UUID of the data-warehouse saved query (materialized view) to read values from. Mutually exclusive with external_data_schema.'
            ),
        external_data_schema: zod
            .uuid()
            .nullish()
            .describe(
                'Person and group sources only: UUID of the warehouse schema (raw incremental table) to read from. Mutually exclusive with saved_query.'
            ),
        source_column: zod
            .string()
            .max(customPropertySourceApiSourceColumnMax)
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
                "Person sources only: {warehouse_column: description} giving each mapped column a human-facing description, seeded from the warehouse column's information_schema description. Optional per column. Create-only."
            ),
        key_column: zod
            .string()
            .max(customPropertySourceApiKeyColumnMax)
            .describe(
                "Column whose value identifies the target: an account's external_id for account sources, the person's distinct_id for person sources, or the group key for group sources."
            ),
        is_enabled: zod
            .boolean()
            .default(customPropertySourceApiIsEnabledDefault)
            .describe(
                'Whether the source syncs. Auto-disabled after repeated failures or a missing view; re-enabling resets the failure count.'
            ),
        consecutive_failures: zod
            .number()
            .describe('Consecutive failed sync runs; the source auto-disables at the cap.'),
        last_synced_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('When the most recent sync run finished.'),
        last_sync_error: zod.string().nullable().describe('Error summary from the last run, or null if it succeeded.'),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: zod.number().nullable(),
        updated_at: zod.iso.datetime({ offset: true }).nullable(),
        sync_frequency_interval_seconds: zod
            .number()
            .nullable()
            .describe(
                'Person and group sources only: how often the underlying warehouse schema syncs, in seconds. Null for account sources or when unavailable.'
            ),
        next_sync_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe(
                'Person and group sources only: approximate time of the next scheduled sync (last synced + interval). Approximate — drifts if the schedule was paused. Null for account sources or if never synced.'
            ),
        latest_run: zod
            .union([CustomPropertySyncRunApi, zod.null()])
            .describe('Person and group sources only: the most recent sync\/backfill run, or null if none yet.'),
    })
    .describe(
        'Binds a data-warehouse source to a custom property definition. Account sources read a\nmaterialized view column and sync onto matching accounts; person and group sources read a\nwarehouse schema and sync onto matching persons or groups on each warehouse sync.'
    )

export type CustomPropertySourceApi = zod.input<typeof CustomPropertySourceApi>
export type CustomPropertySourceApiOutput = zod.output<typeof CustomPropertySourceApi>

export const CustomPropertyReferenceApi = zod
    .object({
        id: zod.string().describe('Id of the referring entity (e.g. the workflow id).'),
        name: zod.string().describe('Display name of the referring entity.'),
        status: zod.string().describe('Status of the referring entity (e.g. workflow status).'),
        type: zod.string().describe("Kind of reference. Currently always 'workflow'."),
    })
    .describe('A place that uses a custom property definition (read-only).')

export type CustomPropertyReferenceApi = zod.input<typeof CustomPropertyReferenceApi>
export type CustomPropertyReferenceApiOutput = zod.output<typeof CustomPropertyReferenceApi>

export const customPropertyDefinitionApiNameMax = 400

export const customPropertyDefinitionApiTargetTypeDefault = `account`
export const customPropertyDefinitionApiGroupTypeIndexMin = 0
export const customPropertyDefinitionApiGroupTypeIndexMax = 4

export const customPropertyDefinitionApiIsBigNumberDefault = false

export const CustomPropertyDefinitionApi = zod
    .object({
        id: zod.uuid(),
        name: zod
            .string()
            .max(customPropertyDefinitionApiNameMax)
            .describe('Human-readable name of the custom property. Unique within the team.'),
        description: zod.string().nullish().describe('Optional description of what the property represents.'),
        display_type: CustomPropertyDisplayTypeEnumApi.describe(
            "How the property is interpreted and rendered: 'text', 'number', 'currency', 'percent', 'date', 'datetime', 'boolean', or 'select'.\n\n\* `text` - text\n\* `number` - number\n\* `currency` - currency\n\* `percent` - percent\n\* `date` - date\n\* `datetime` - datetime\n\* `boolean` - boolean\n\* `select` - select"
        ),
        target_type: CustomPropertyDefinitionTargetTypeEnumApi.default(
            customPropertyDefinitionApiTargetTypeDefault
        ).describe(
            "What entity this property is attached to: 'account' (default), 'person', or 'group'. Person and group properties are populated from a warehouse schema and become usable like any other person\/group property (feature flags, cohorts, insights).\n\n\* `account` - account\n\* `person` - person\n\* `group` - group"
        ),
        group_type_index: zod
            .number()
            .min(customPropertyDefinitionApiGroupTypeIndexMin)
            .max(customPropertyDefinitionApiGroupTypeIndexMax)
            .nullish()
            .describe(
                "For 'group' targets only: which group type (0-4) the property attaches to. Required when target_type is 'group'; must be omitted otherwise. Create-only."
            ),
        is_big_number: zod
            .boolean()
            .default(customPropertyDefinitionApiIsBigNumberDefault)
            .describe('Abbreviate large numbers (e.g. 10,000 → 10K). Only applies to numeric properties.'),
        is_canonical: zod
            .boolean()
            .describe(
                'True when PostHog writes this property itself. Its name and display type are fixed — an update changing either is rejected.'
            ),
        options: zod
            .array(CustomPropertyOptionApi)
            .nullish()
            .describe(
                "For select properties: the allowed options. Required (non-empty) when display_type is 'select'; cleared server-side for other types."
            ),
        source: zod
            .union([CustomPropertySourceApi, zod.null()])
            .describe(
                'The data-warehouse view-sync binding feeding this property, or null when values are set manually.'
            ),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: zod.number().nullable(),
        updated_at: zod.iso.datetime({ offset: true }).nullable(),
        references: zod
            .array(CustomPropertyReferenceApi)
            .describe('Workflows that use this property, resolved by definition id.'),
    })
    .describe(
        "A team-scoped definition of a custom account property — the attribute side of the model.\n\nHolds only the property's shape (name, display type, big-number flag). Per-account values are\nstored separately, so this serializer never reads or writes account values."
    )

export type CustomPropertyDefinitionApi = zod.input<typeof CustomPropertyDefinitionApi>
export type CustomPropertyDefinitionApiOutput = zod.output<typeof CustomPropertyDefinitionApi>

export const PaginatedCustomPropertyDefinitionListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(CustomPropertyDefinitionApi),
})

export type PaginatedCustomPropertyDefinitionListApi = zod.input<typeof PaginatedCustomPropertyDefinitionListApi>
export type PaginatedCustomPropertyDefinitionListApiOutput = zod.output<typeof PaginatedCustomPropertyDefinitionListApi>

export const patchedCustomPropertyDefinitionApiNameMax = 400

export const patchedCustomPropertyDefinitionApiTargetTypeDefault = `account`
export const patchedCustomPropertyDefinitionApiGroupTypeIndexMin = 0
export const patchedCustomPropertyDefinitionApiGroupTypeIndexMax = 4

export const patchedCustomPropertyDefinitionApiIsBigNumberDefault = false

export const PatchedCustomPropertyDefinitionApi = zod
    .object({
        id: zod.uuid().optional(),
        name: zod
            .string()
            .max(patchedCustomPropertyDefinitionApiNameMax)
            .optional()
            .describe('Human-readable name of the custom property. Unique within the team.'),
        description: zod.string().nullish().describe('Optional description of what the property represents.'),
        display_type: CustomPropertyDisplayTypeEnumApi.optional().describe(
            "How the property is interpreted and rendered: 'text', 'number', 'currency', 'percent', 'date', 'datetime', 'boolean', or 'select'.\n\n\* `text` - text\n\* `number` - number\n\* `currency` - currency\n\* `percent` - percent\n\* `date` - date\n\* `datetime` - datetime\n\* `boolean` - boolean\n\* `select` - select"
        ),
        target_type: CustomPropertyDefinitionTargetTypeEnumApi.default(
            patchedCustomPropertyDefinitionApiTargetTypeDefault
        ).describe(
            "What entity this property is attached to: 'account' (default), 'person', or 'group'. Person and group properties are populated from a warehouse schema and become usable like any other person\/group property (feature flags, cohorts, insights).\n\n\* `account` - account\n\* `person` - person\n\* `group` - group"
        ),
        group_type_index: zod
            .number()
            .min(patchedCustomPropertyDefinitionApiGroupTypeIndexMin)
            .max(patchedCustomPropertyDefinitionApiGroupTypeIndexMax)
            .nullish()
            .describe(
                "For 'group' targets only: which group type (0-4) the property attaches to. Required when target_type is 'group'; must be omitted otherwise. Create-only."
            ),
        is_big_number: zod
            .boolean()
            .default(patchedCustomPropertyDefinitionApiIsBigNumberDefault)
            .describe('Abbreviate large numbers (e.g. 10,000 → 10K). Only applies to numeric properties.'),
        is_canonical: zod
            .boolean()
            .optional()
            .describe(
                'True when PostHog writes this property itself. Its name and display type are fixed — an update changing either is rejected.'
            ),
        options: zod
            .array(CustomPropertyOptionApi)
            .nullish()
            .describe(
                "For select properties: the allowed options. Required (non-empty) when display_type is 'select'; cleared server-side for other types."
            ),
        source: zod
            .union([CustomPropertySourceApi, zod.null()])
            .optional()
            .describe(
                'The data-warehouse view-sync binding feeding this property, or null when values are set manually.'
            ),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        created_by: zod.number().nullish(),
        updated_at: zod.iso.datetime({ offset: true }).nullish(),
        references: zod
            .array(CustomPropertyReferenceApi)
            .optional()
            .describe('Workflows that use this property, resolved by definition id.'),
    })
    .describe(
        "A team-scoped definition of a custom account property — the attribute side of the model.\n\nHolds only the property's shape (name, display type, big-number flag). Per-account values are\nstored separately, so this serializer never reads or writes account values."
    )

export type PatchedCustomPropertyDefinitionApi = zod.input<typeof PatchedCustomPropertyDefinitionApi>
export type PatchedCustomPropertyDefinitionApiOutput = zod.output<typeof PatchedCustomPropertyDefinitionApi>

export const CustomPropertyValueSuggestionApi = zod
    .object({
        name: zod.string().describe('A suggested value for the custom property.'),
    })
    .describe('One suggested filter value for a custom property.')

export type CustomPropertyValueSuggestionApi = zod.input<typeof CustomPropertyValueSuggestionApi>
export type CustomPropertyValueSuggestionApiOutput = zod.output<typeof CustomPropertyValueSuggestionApi>

export const CustomPropertyValueSuggestionsResponseApi = zod
    .object({
        results: zod.array(CustomPropertyValueSuggestionApi).describe('Suggested values matching the search input.'),
        refreshing: zod
            .boolean()
            .describe('Always false — present for compatibility with the property-values consumer.'),
    })
    .describe(
        'Response shape of the custom property value-suggestions endpoint.\n\nMatches the contract of the shared property-values picker (``propertyDefinitionsModel``\non the frontend), which expects ``{results: [{name}], refreshing}``.'
    )

export type CustomPropertyValueSuggestionsResponseApi = zod.input<typeof CustomPropertyValueSuggestionsResponseApi>
export type CustomPropertyValueSuggestionsResponseApiOutput = zod.output<
    typeof CustomPropertyValueSuggestionsResponseApi
>

export const PaginatedCustomPropertySourceListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(CustomPropertySourceApi),
})

export type PaginatedCustomPropertySourceListApi = zod.input<typeof PaginatedCustomPropertySourceListApi>
export type PaginatedCustomPropertySourceListApiOutput = zod.output<typeof PaginatedCustomPropertySourceListApi>

export const customPropertySourceUpdateApiSourceColumnMax = 400

export const customPropertySourceUpdateApiKeyColumnMax = 400

export const CustomPropertySourceUpdateApi = zod
    .object({
        source_column: zod
            .string()
            .max(customPropertySourceUpdateApiSourceColumnMax)
            .optional()
            .describe('Column in the view whose value is written to the property.'),
        key_column: zod
            .string()
            .max(customPropertySourceUpdateApiKeyColumnMax)
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

export type CustomPropertySourceUpdateApi = zod.input<typeof CustomPropertySourceUpdateApi>
export type CustomPropertySourceUpdateApiOutput = zod.output<typeof CustomPropertySourceUpdateApi>

export const patchedCustomPropertySourceUpdateApiSourceColumnMax = 400

export const patchedCustomPropertySourceUpdateApiKeyColumnMax = 400

export const PatchedCustomPropertySourceUpdateApi = zod
    .object({
        source_column: zod
            .string()
            .max(patchedCustomPropertySourceUpdateApiSourceColumnMax)
            .optional()
            .describe('Column in the view whose value is written to the property.'),
        key_column: zod
            .string()
            .max(patchedCustomPropertySourceUpdateApiKeyColumnMax)
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

export type PatchedCustomPropertySourceUpdateApi = zod.input<typeof PatchedCustomPropertySourceUpdateApi>
export type PatchedCustomPropertySourceUpdateApiOutput = zod.output<typeof PatchedCustomPropertySourceUpdateApi>

export const CustomPropertySyncTriggerResponseStatusEnumApi = zod
    .enum(['triggered', 'started', 'already_running'])
    .describe('\* `triggered` - triggered\n\* `started` - started\n\* `already_running` - already_running')

export type CustomPropertySyncTriggerResponseStatusEnumApi = zod.input<
    typeof CustomPropertySyncTriggerResponseStatusEnumApi
>
export type CustomPropertySyncTriggerResponseStatusEnumApiOutput = zod.output<
    typeof CustomPropertySyncTriggerResponseStatusEnumApi
>

export const CustomPropertySyncTriggerResponseApi = zod
    .object({
        status: CustomPropertySyncTriggerResponseStatusEnumApi.describe(
            "'triggered' (sync now started the warehouse sync), 'started' (a new backfill began), or 'already_running' (a backfill for this table was already in flight, so this was a no-op).\n\n\* `triggered` - triggered\n\* `started` - started\n\* `already_running` - already_running"
        ),
        already_running: zod
            .boolean()
            .optional()
            .describe(
                'Backfill only: true when a backfill for this table was already running and this call coalesced.'
            ),
    })
    .describe('Response of the person\/group-property sync\/backfill trigger actions.')

export type CustomPropertySyncTriggerResponseApi = zod.input<typeof CustomPropertySyncTriggerResponseApi>
export type CustomPropertySyncTriggerResponseApiOutput = zod.output<typeof CustomPropertySyncTriggerResponseApi>

export const PaginatedCustomPropertySyncRunListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(CustomPropertySyncRunApi),
})

export type PaginatedCustomPropertySyncRunListApi = zod.input<typeof PaginatedCustomPropertySyncRunListApi>
export type PaginatedCustomPropertySyncRunListApiOutput = zod.output<typeof PaginatedCustomPropertySyncRunListApi>

export const customerJourneyApiNameMax = 400

export const CustomerJourneyApi = zod.object({
    id: zod.uuid(),
    insight: zod.number(),
    name: zod.string().max(customerJourneyApiNameMax),
    description: zod.string().nullish(),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: zod.number().nullable(),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type CustomerJourneyApi = zod.input<typeof CustomerJourneyApi>
export type CustomerJourneyApiOutput = zod.output<typeof CustomerJourneyApi>

export const PaginatedCustomerJourneyListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(CustomerJourneyApi),
})

export type PaginatedCustomerJourneyListApi = zod.input<typeof PaginatedCustomerJourneyListApi>
export type PaginatedCustomerJourneyListApiOutput = zod.output<typeof PaginatedCustomerJourneyListApi>

export const patchedCustomerJourneyApiNameMax = 400

export const PatchedCustomerJourneyApi = zod.object({
    id: zod.uuid().optional(),
    insight: zod.number().optional(),
    name: zod.string().max(patchedCustomerJourneyApiNameMax).optional(),
    description: zod.string().nullish(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: zod.number().nullish(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
})

export type PatchedCustomerJourneyApi = zod.input<typeof PatchedCustomerJourneyApi>
export type PatchedCustomerJourneyApiOutput = zod.output<typeof PatchedCustomerJourneyApi>

export const CustomerProfileConfigScopeEnumApi = zod
    .enum(['person', 'group_0', 'group_1', 'group_2', 'group_3', 'group_4'])
    .describe(
        '\* `person` - Person\n\* `group_0` - Group 0\n\* `group_1` - Group 1\n\* `group_2` - Group 2\n\* `group_3` - Group 3\n\* `group_4` - Group 4'
    )

export type CustomerProfileConfigScopeEnumApi = zod.input<typeof CustomerProfileConfigScopeEnumApi>
export type CustomerProfileConfigScopeEnumApiOutput = zod.output<typeof CustomerProfileConfigScopeEnumApi>

export const CustomerProfileConfigApi = zod.object({
    id: zod.uuid(),
    scope: CustomerProfileConfigScopeEnumApi,
    content: zod.unknown().optional(),
    sidebar: zod.unknown().optional(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type CustomerProfileConfigApi = zod.input<typeof CustomerProfileConfigApi>
export type CustomerProfileConfigApiOutput = zod.output<typeof CustomerProfileConfigApi>

export const PaginatedCustomerProfileConfigListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(CustomerProfileConfigApi),
})

export type PaginatedCustomerProfileConfigListApi = zod.input<typeof PaginatedCustomerProfileConfigListApi>
export type PaginatedCustomerProfileConfigListApiOutput = zod.output<typeof PaginatedCustomerProfileConfigListApi>

export const PatchedCustomerProfileConfigApi = zod.object({
    id: zod.uuid().optional(),
    scope: CustomerProfileConfigScopeEnumApi.optional(),
    content: zod.unknown().optional(),
    sidebar: zod.unknown().optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
})

export type PatchedCustomerProfileConfigApi = zod.input<typeof PatchedCustomerProfileConfigApi>
export type PatchedCustomerProfileConfigApiOutput = zod.output<typeof PatchedCustomerProfileConfigApi>

export const eventStreamApiEnabledDefault = false
export const eventStreamApiEventNamesItemMax = 400

export const eventStreamApiSlackChannelIdDefault = ``
export const eventStreamApiSlackChannelIdMax = 200

export const eventStreamApiSlackChannelNameDefault = ``
export const eventStreamApiSlackChannelNameMax = 200

export const EventStreamApi = zod
    .object({
        id: zod.uuid(),
        enabled: zod
            .boolean()
            .default(eventStreamApiEnabledDefault)
            .describe(
                'Whether the stream delivers to Slack. Delivery also requires at least one event, at least one member account with an external ID, and a Slack workspace + channel.'
            ),
        event_names: zod
            .array(zod.string().max(eventStreamApiEventNamesItemMax))
            .optional()
            .describe('Names of the events to stream (matched exactly). Duplicates and blanks are dropped.'),
        slack_integration: zod
            .number()
            .nullish()
            .describe("ID of the team's Slack workspace integration to deliver through."),
        slack_channel_id: zod
            .string()
            .max(eventStreamApiSlackChannelIdMax)
            .default(eventStreamApiSlackChannelIdDefault)
            .describe('Slack channel ID to post to (e.g. C0123ABC).'),
        slack_channel_name: zod
            .string()
            .max(eventStreamApiSlackChannelNameMax)
            .default(eventStreamApiSlackChannelNameDefault)
            .describe('Display name of the Slack channel (e.g. #customer-events). Informational only.'),
        account_ids: zod
            .array(zod.uuid())
            .describe(
                "UUIDs of the member accounts whose users' events are streamed. Managed via the add_account\/remove_account endpoints."
            ),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: zod.number().nullable(),
        updated_at: zod.iso.datetime({ offset: true }).nullable(),
    })
    .describe(
        "The caller's event stream — a live feed of selected accounts' events posted to a\nSlack channel of their choice. One stream per user per project."
    )

export type EventStreamApi = zod.input<typeof EventStreamApi>
export type EventStreamApiOutput = zod.output<typeof EventStreamApi>

export const patchedEventStreamApiEnabledDefault = false
export const patchedEventStreamApiEventNamesItemMax = 400

export const patchedEventStreamApiSlackChannelIdDefault = ``
export const patchedEventStreamApiSlackChannelIdMax = 200

export const patchedEventStreamApiSlackChannelNameDefault = ``
export const patchedEventStreamApiSlackChannelNameMax = 200

export const PatchedEventStreamApi = zod
    .object({
        id: zod.uuid().optional(),
        enabled: zod
            .boolean()
            .default(patchedEventStreamApiEnabledDefault)
            .describe(
                'Whether the stream delivers to Slack. Delivery also requires at least one event, at least one member account with an external ID, and a Slack workspace + channel.'
            ),
        event_names: zod
            .array(zod.string().max(patchedEventStreamApiEventNamesItemMax))
            .optional()
            .describe('Names of the events to stream (matched exactly). Duplicates and blanks are dropped.'),
        slack_integration: zod
            .number()
            .nullish()
            .describe("ID of the team's Slack workspace integration to deliver through."),
        slack_channel_id: zod
            .string()
            .max(patchedEventStreamApiSlackChannelIdMax)
            .default(patchedEventStreamApiSlackChannelIdDefault)
            .describe('Slack channel ID to post to (e.g. C0123ABC).'),
        slack_channel_name: zod
            .string()
            .max(patchedEventStreamApiSlackChannelNameMax)
            .default(patchedEventStreamApiSlackChannelNameDefault)
            .describe('Display name of the Slack channel (e.g. #customer-events). Informational only.'),
        account_ids: zod
            .array(zod.uuid())
            .optional()
            .describe(
                "UUIDs of the member accounts whose users' events are streamed. Managed via the add_account\/remove_account endpoints."
            ),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        created_by: zod.number().nullish(),
        updated_at: zod.iso.datetime({ offset: true }).nullish(),
    })
    .describe(
        "The caller's event stream — a live feed of selected accounts' events posted to a\nSlack channel of their choice. One stream per user per project."
    )

export type PatchedEventStreamApi = zod.input<typeof PatchedEventStreamApi>
export type PatchedEventStreamApiOutput = zod.output<typeof PatchedEventStreamApi>

export const EventStreamMemberWriteApi = zod
    .object({
        account_id: zod.uuid().describe('UUID of the account to add to or remove from the stream.'),
    })
    .describe('Request body for adding or removing an event-stream member account.')

export type EventStreamMemberWriteApi = zod.input<typeof EventStreamMemberWriteApi>
export type EventStreamMemberWriteApiOutput = zod.output<typeof EventStreamMemberWriteApi>

export const EventStreamTestMessageApi = zod
    .object({
        channel_id: zod.string().describe('Slack channel ID the test message was posted to (e.g. C0123ABC).'),
    })
    .describe('Result of posting an event-stream test message to Slack.')

export type EventStreamTestMessageApi = zod.input<typeof EventStreamTestMessageApi>
export type EventStreamTestMessageApiOutput = zod.output<typeof EventStreamTestMessageApi>

export const GroupUsageMetricFormatEnumApi = zod
    .enum(['numeric', 'currency'])
    .describe('\* `numeric` - numeric\n\* `currency` - currency')

export type GroupUsageMetricFormatEnumApi = zod.input<typeof GroupUsageMetricFormatEnumApi>
export type GroupUsageMetricFormatEnumApiOutput = zod.output<typeof GroupUsageMetricFormatEnumApi>

export const GroupUsageMetricDisplayEnumApi = zod
    .enum(['number', 'sparkline'])
    .describe('\* `number` - number\n\* `sparkline` - sparkline')

export type GroupUsageMetricDisplayEnumApi = zod.input<typeof GroupUsageMetricDisplayEnumApi>
export type GroupUsageMetricDisplayEnumApiOutput = zod.output<typeof GroupUsageMetricDisplayEnumApi>

export const MathEnumApi = zod.enum(['count', 'sum']).describe('\* `count` - count\n\* `sum` - sum')

export type MathEnumApi = zod.input<typeof MathEnumApi>
export type MathEnumApiOutput = zod.output<typeof MathEnumApi>

export const groupUsageMetricApiNameMax = 255

export const groupUsageMetricApiFormatDefault = `numeric`
export const groupUsageMetricApiIntervalDefault = 7
export const groupUsageMetricApiDisplayDefault = `number`
export const groupUsageMetricApiMathDefault = `count`
export const groupUsageMetricApiMathPropertyMax = 255

export const GroupUsageMetricApi = zod.object({
    id: zod.uuid(),
    name: zod
        .string()
        .max(groupUsageMetricApiNameMax)
        .describe('Name of the usage metric. Must be unique per group type within the project.'),
    format: GroupUsageMetricFormatEnumApi.default(groupUsageMetricApiFormatDefault).describe(
        'How the metric value is formatted in the UI. One of `numeric` or `currency`.\n\n\* `numeric` - numeric\n\* `currency` - currency'
    ),
    interval: zod
        .number()
        .default(groupUsageMetricApiIntervalDefault)
        .describe('Rolling time window in days used to compute the metric. Defaults to 7.'),
    display: GroupUsageMetricDisplayEnumApi.default(groupUsageMetricApiDisplayDefault).describe(
        'Visual representation in the UI. One of `number` or `sparkline`.\n\n\* `number` - number\n\* `sparkline` - sparkline'
    ),
    filters: zod
        .record(zod.string(), zod.unknown())
        .describe(
            'Filter definition for the metric. Two shapes are accepted, discriminated by an optional `source` key.\n\n\*\*Events\*\* (default, when `source` is missing or `\"events\"`): HogFunction filter shape — `events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.\n\n\*\*Data warehouse\*\* (`source: \"data_warehouse\"`): `table_name` (synced DW table), `timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value matches the entity key). Currently DW metrics only render on group profiles — person profiles are not yet supported.'
        ),
    math: MathEnumApi.default(groupUsageMetricApiMathDefault).describe(
        'Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` on matching events.\n\n\* `count` - count\n\* `sum` - sum'
    ),
    math_property: zod
        .string()
        .max(groupUsageMetricApiMathPropertyMax)
        .nullish()
        .describe(
            'Required when `math` is `sum`; must be empty when `math` is `count`. For events metrics this is an event property name. For data warehouse metrics this is the column name (or HogQL expression) to sum on the DW table.'
        ),
})

export type GroupUsageMetricApi = zod.input<typeof GroupUsageMetricApi>
export type GroupUsageMetricApiOutput = zod.output<typeof GroupUsageMetricApi>

export const PaginatedGroupUsageMetricListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(GroupUsageMetricApi),
})

export type PaginatedGroupUsageMetricListApi = zod.input<typeof PaginatedGroupUsageMetricListApi>
export type PaginatedGroupUsageMetricListApiOutput = zod.output<typeof PaginatedGroupUsageMetricListApi>

export const patchedGroupUsageMetricApiNameMax = 255

export const patchedGroupUsageMetricApiFormatDefault = `numeric`
export const patchedGroupUsageMetricApiIntervalDefault = 7
export const patchedGroupUsageMetricApiDisplayDefault = `number`
export const patchedGroupUsageMetricApiMathDefault = `count`
export const patchedGroupUsageMetricApiMathPropertyMax = 255

export const PatchedGroupUsageMetricApi = zod.object({
    id: zod.uuid().optional(),
    name: zod
        .string()
        .max(patchedGroupUsageMetricApiNameMax)
        .optional()
        .describe('Name of the usage metric. Must be unique per group type within the project.'),
    format: GroupUsageMetricFormatEnumApi.default(patchedGroupUsageMetricApiFormatDefault).describe(
        'How the metric value is formatted in the UI. One of `numeric` or `currency`.\n\n\* `numeric` - numeric\n\* `currency` - currency'
    ),
    interval: zod
        .number()
        .default(patchedGroupUsageMetricApiIntervalDefault)
        .describe('Rolling time window in days used to compute the metric. Defaults to 7.'),
    display: GroupUsageMetricDisplayEnumApi.default(patchedGroupUsageMetricApiDisplayDefault).describe(
        'Visual representation in the UI. One of `number` or `sparkline`.\n\n\* `number` - number\n\* `sparkline` - sparkline'
    ),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Filter definition for the metric. Two shapes are accepted, discriminated by an optional `source` key.\n\n\*\*Events\*\* (default, when `source` is missing or `\"events\"`): HogFunction filter shape — `events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.\n\n\*\*Data warehouse\*\* (`source: \"data_warehouse\"`): `table_name` (synced DW table), `timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value matches the entity key). Currently DW metrics only render on group profiles — person profiles are not yet supported.'
        ),
    math: MathEnumApi.default(patchedGroupUsageMetricApiMathDefault).describe(
        'Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` on matching events.\n\n\* `count` - count\n\* `sum` - sum'
    ),
    math_property: zod
        .string()
        .max(patchedGroupUsageMetricApiMathPropertyMax)
        .nullish()
        .describe(
            'Required when `math` is `sum`; must be empty when `math` is `count`. For events metrics this is an event property name. For data warehouse metrics this is the column name (or HogQL expression) to sum on the DW table.'
        ),
})

export type PatchedGroupUsageMetricApi = zod.input<typeof PatchedGroupUsageMetricApi>
export type PatchedGroupUsageMetricApiOutput = zod.output<typeof PatchedGroupUsageMetricApi>
