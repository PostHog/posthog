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

export const PropertyFilterTypeEnumApi = zod
    .enum([
        'event',
        'event_metadata',
        'feature',
        'person',
        'person_metadata',
        'cohort',
        'element',
        'static-cohort',
        'dynamic-cohort',
        'precalculated-cohort',
        'group',
        'recording',
        'log_entry',
        'behavioral',
        'session',
        'hogql',
        'data_warehouse',
        'data_warehouse_person_property',
        'error_tracking_issue',
        'log',
        'log_attribute',
        'log_resource_attribute',
        'metric_attribute',
        'span',
        'span_attribute',
        'span_resource_attribute',
        'revenue_analytics',
        'account_custom_property',
        'flag',
        'workflow_variable',
    ])
    .describe(
        '\* `event` - event\n\* `event_metadata` - event_metadata\n\* `feature` - feature\n\* `person` - person\n\* `person_metadata` - person_metadata\n\* `cohort` - cohort\n\* `element` - element\n\* `static-cohort` - static-cohort\n\* `dynamic-cohort` - dynamic-cohort\n\* `precalculated-cohort` - precalculated-cohort\n\* `group` - group\n\* `recording` - recording\n\* `log_entry` - log_entry\n\* `behavioral` - behavioral\n\* `session` - session\n\* `hogql` - hogql\n\* `data_warehouse` - data_warehouse\n\* `data_warehouse_person_property` - data_warehouse_person_property\n\* `error_tracking_issue` - error_tracking_issue\n\* `log` - log\n\* `log_attribute` - log_attribute\n\* `log_resource_attribute` - log_resource_attribute\n\* `metric_attribute` - metric_attribute\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute\n\* `revenue_analytics` - revenue_analytics\n\* `account_custom_property` - account_custom_property\n\* `flag` - flag\n\* `workflow_variable` - workflow_variable'
    )

export type PropertyFilterTypeEnumApi = zod.input<typeof PropertyFilterTypeEnumApi>
export type PropertyFilterTypeEnumApiOutput = zod.output<typeof PropertyFilterTypeEnumApi>

export const StringMatchOperatorEnumApi = zod
    .enum([
        'exact',
        'is_not',
        'icontains',
        'not_icontains',
        'starts_with',
        'not_starts_with',
        'ends_with',
        'not_ends_with',
        'regex',
        'not_regex',
    ])
    .describe(
        '\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex'
    )

export type StringMatchOperatorEnumApi = zod.input<typeof StringMatchOperatorEnumApi>
export type StringMatchOperatorEnumApiOutput = zod.output<typeof StringMatchOperatorEnumApi>

export const stringPropertyFilterApiTypeDefault = `event`
export const stringPropertyFilterApiOperatorDefault = `exact`

export const StringPropertyFilterApi = zod
    .object({
        key: zod.string().describe("Key of the property you're filtering on. For example `email` or `$current_url`."),
        type: PropertyFilterTypeEnumApi.default(stringPropertyFilterApiTypeDefault).describe(
            'Property type (event, person, session, etc.).\n\n\* `event` - event\n\* `event_metadata` - event_metadata\n\* `feature` - feature\n\* `person` - person\n\* `person_metadata` - person_metadata\n\* `cohort` - cohort\n\* `element` - element\n\* `static-cohort` - static-cohort\n\* `dynamic-cohort` - dynamic-cohort\n\* `precalculated-cohort` - precalculated-cohort\n\* `group` - group\n\* `recording` - recording\n\* `log_entry` - log_entry\n\* `behavioral` - behavioral\n\* `session` - session\n\* `hogql` - hogql\n\* `data_warehouse` - data_warehouse\n\* `data_warehouse_person_property` - data_warehouse_person_property\n\* `error_tracking_issue` - error_tracking_issue\n\* `log` - log\n\* `log_attribute` - log_attribute\n\* `log_resource_attribute` - log_resource_attribute\n\* `metric_attribute` - metric_attribute\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute\n\* `revenue_analytics` - revenue_analytics\n\* `account_custom_property` - account_custom_property\n\* `flag` - flag\n\* `workflow_variable` - workflow_variable'
        ),
        value: zod.string().describe('String value to match against.'),
        operator: StringMatchOperatorEnumApi.default(stringPropertyFilterApiOperatorDefault).describe(
            'String comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `icontains` - icontains\n\* `not_icontains` - not_icontains\n\* `starts_with` - starts_with\n\* `not_starts_with` - not_starts_with\n\* `ends_with` - ends_with\n\* `not_ends_with` - not_ends_with\n\* `regex` - regex\n\* `not_regex` - not_regex'
        ),
    })
    .describe('Matches string values with text-oriented operators.')

export type StringPropertyFilterApi = zod.input<typeof StringPropertyFilterApi>
export type StringPropertyFilterApiOutput = zod.output<typeof StringPropertyFilterApi>

export const NumericPropertyFilterOperatorEnumApi = zod
    .enum(['exact', 'is_not', 'gt', 'lt', 'gte', 'lte'])
    .describe('\* `exact` - exact\n\* `is_not` - is_not\n\* `gt` - gt\n\* `lt` - lt\n\* `gte` - gte\n\* `lte` - lte')

export type NumericPropertyFilterOperatorEnumApi = zod.input<typeof NumericPropertyFilterOperatorEnumApi>
export type NumericPropertyFilterOperatorEnumApiOutput = zod.output<typeof NumericPropertyFilterOperatorEnumApi>

export const numericPropertyFilterApiTypeDefault = `event`
export const numericPropertyFilterApiOperatorDefault = `exact`

export const NumericPropertyFilterApi = zod
    .object({
        key: zod.string().describe("Key of the property you're filtering on. For example `email` or `$current_url`."),
        type: PropertyFilterTypeEnumApi.default(numericPropertyFilterApiTypeDefault).describe(
            'Property type (event, person, session, etc.).\n\n\* `event` - event\n\* `event_metadata` - event_metadata\n\* `feature` - feature\n\* `person` - person\n\* `person_metadata` - person_metadata\n\* `cohort` - cohort\n\* `element` - element\n\* `static-cohort` - static-cohort\n\* `dynamic-cohort` - dynamic-cohort\n\* `precalculated-cohort` - precalculated-cohort\n\* `group` - group\n\* `recording` - recording\n\* `log_entry` - log_entry\n\* `behavioral` - behavioral\n\* `session` - session\n\* `hogql` - hogql\n\* `data_warehouse` - data_warehouse\n\* `data_warehouse_person_property` - data_warehouse_person_property\n\* `error_tracking_issue` - error_tracking_issue\n\* `log` - log\n\* `log_attribute` - log_attribute\n\* `log_resource_attribute` - log_resource_attribute\n\* `metric_attribute` - metric_attribute\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute\n\* `revenue_analytics` - revenue_analytics\n\* `account_custom_property` - account_custom_property\n\* `flag` - flag\n\* `workflow_variable` - workflow_variable'
        ),
        value: zod.number().describe('Numeric value to compare against.'),
        operator: NumericPropertyFilterOperatorEnumApi.default(numericPropertyFilterApiOperatorDefault).describe(
            'Numeric comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `gt` - gt\n\* `lt` - lt\n\* `gte` - gte\n\* `lte` - lte'
        ),
    })
    .describe('Matches numeric values with comparison operators.')

export type NumericPropertyFilterApi = zod.input<typeof NumericPropertyFilterApi>
export type NumericPropertyFilterApiOutput = zod.output<typeof NumericPropertyFilterApi>

export const ArrayPropertyFilterOperatorEnumApi = zod
    .enum(['exact', 'is_not', 'in', 'not_in'])
    .describe('\* `exact` - exact\n\* `is_not` - is_not\n\* `in` - in\n\* `not_in` - not_in')

export type ArrayPropertyFilterOperatorEnumApi = zod.input<typeof ArrayPropertyFilterOperatorEnumApi>
export type ArrayPropertyFilterOperatorEnumApiOutput = zod.output<typeof ArrayPropertyFilterOperatorEnumApi>

export const arrayPropertyFilterApiTypeDefault = `event`
export const arrayPropertyFilterApiOperatorDefault = `exact`

export const ArrayPropertyFilterApi = zod
    .object({
        key: zod.string().describe("Key of the property you're filtering on. For example `email` or `$current_url`."),
        type: PropertyFilterTypeEnumApi.default(arrayPropertyFilterApiTypeDefault).describe(
            'Property type (event, person, session, etc.).\n\n\* `event` - event\n\* `event_metadata` - event_metadata\n\* `feature` - feature\n\* `person` - person\n\* `person_metadata` - person_metadata\n\* `cohort` - cohort\n\* `element` - element\n\* `static-cohort` - static-cohort\n\* `dynamic-cohort` - dynamic-cohort\n\* `precalculated-cohort` - precalculated-cohort\n\* `group` - group\n\* `recording` - recording\n\* `log_entry` - log_entry\n\* `behavioral` - behavioral\n\* `session` - session\n\* `hogql` - hogql\n\* `data_warehouse` - data_warehouse\n\* `data_warehouse_person_property` - data_warehouse_person_property\n\* `error_tracking_issue` - error_tracking_issue\n\* `log` - log\n\* `log_attribute` - log_attribute\n\* `log_resource_attribute` - log_resource_attribute\n\* `metric_attribute` - metric_attribute\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute\n\* `revenue_analytics` - revenue_analytics\n\* `account_custom_property` - account_custom_property\n\* `flag` - flag\n\* `workflow_variable` - workflow_variable'
        ),
        value: zod
            .array(zod.string())
            .describe('List of values to match. For example `[\"test@example.com\", \"ok@example.com\"]`.'),
        operator: ArrayPropertyFilterOperatorEnumApi.default(arrayPropertyFilterApiOperatorDefault).describe(
            'Array comparison operator.\n\n\* `exact` - exact\n\* `is_not` - is_not\n\* `in` - in\n\* `not_in` - not_in'
        ),
    })
    .describe('Matches against a list of values (OR semantics for exact\/is_not, set membership for in\/not_in).')

export type ArrayPropertyFilterApi = zod.input<typeof ArrayPropertyFilterApi>
export type ArrayPropertyFilterApiOutput = zod.output<typeof ArrayPropertyFilterApi>

export const DateOperatorEnumApi = zod
    .enum(['is_date_exact', 'is_date_before', 'is_date_after'])
    .describe(
        '\* `is_date_exact` - is_date_exact\n\* `is_date_before` - is_date_before\n\* `is_date_after` - is_date_after'
    )

export type DateOperatorEnumApi = zod.input<typeof DateOperatorEnumApi>
export type DateOperatorEnumApiOutput = zod.output<typeof DateOperatorEnumApi>

export const datePropertyFilterApiTypeDefault = `event`
export const datePropertyFilterApiOperatorDefault = `is_date_exact`

export const DatePropertyFilterApi = zod
    .object({
        key: zod.string().describe("Key of the property you're filtering on. For example `email` or `$current_url`."),
        type: PropertyFilterTypeEnumApi.default(datePropertyFilterApiTypeDefault).describe(
            'Property type (event, person, session, etc.).\n\n\* `event` - event\n\* `event_metadata` - event_metadata\n\* `feature` - feature\n\* `person` - person\n\* `person_metadata` - person_metadata\n\* `cohort` - cohort\n\* `element` - element\n\* `static-cohort` - static-cohort\n\* `dynamic-cohort` - dynamic-cohort\n\* `precalculated-cohort` - precalculated-cohort\n\* `group` - group\n\* `recording` - recording\n\* `log_entry` - log_entry\n\* `behavioral` - behavioral\n\* `session` - session\n\* `hogql` - hogql\n\* `data_warehouse` - data_warehouse\n\* `data_warehouse_person_property` - data_warehouse_person_property\n\* `error_tracking_issue` - error_tracking_issue\n\* `log` - log\n\* `log_attribute` - log_attribute\n\* `log_resource_attribute` - log_resource_attribute\n\* `metric_attribute` - metric_attribute\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute\n\* `revenue_analytics` - revenue_analytics\n\* `account_custom_property` - account_custom_property\n\* `flag` - flag\n\* `workflow_variable` - workflow_variable'
        ),
        value: zod
            .string()
            .describe("Date or datetime string in ISO 8601 format (e.g. '2024-01-15' or '2024-01-15T10:30:00Z')."),
        operator: DateOperatorEnumApi.default(datePropertyFilterApiOperatorDefault).describe(
            'Date comparison operator.\n\n\* `is_date_exact` - is_date_exact\n\* `is_date_before` - is_date_before\n\* `is_date_after` - is_date_after'
        ),
    })
    .describe('Matches date\/datetime values with date-specific operators.')

export type DatePropertyFilterApi = zod.input<typeof DatePropertyFilterApi>
export type DatePropertyFilterApiOutput = zod.output<typeof DatePropertyFilterApi>

export const ExistenceOperatorEnumApi = zod
    .enum(['is_set', 'is_not_set'])
    .describe('\* `is_set` - is_set\n\* `is_not_set` - is_not_set')

export type ExistenceOperatorEnumApi = zod.input<typeof ExistenceOperatorEnumApi>
export type ExistenceOperatorEnumApiOutput = zod.output<typeof ExistenceOperatorEnumApi>

export const existencePropertyFilterApiTypeDefault = `event`

export const ExistencePropertyFilterApi = zod
    .object({
        key: zod.string().describe("Key of the property you're filtering on. For example `email` or `$current_url`."),
        type: PropertyFilterTypeEnumApi.default(existencePropertyFilterApiTypeDefault).describe(
            'Property type (event, person, session, etc.).\n\n\* `event` - event\n\* `event_metadata` - event_metadata\n\* `feature` - feature\n\* `person` - person\n\* `person_metadata` - person_metadata\n\* `cohort` - cohort\n\* `element` - element\n\* `static-cohort` - static-cohort\n\* `dynamic-cohort` - dynamic-cohort\n\* `precalculated-cohort` - precalculated-cohort\n\* `group` - group\n\* `recording` - recording\n\* `log_entry` - log_entry\n\* `behavioral` - behavioral\n\* `session` - session\n\* `hogql` - hogql\n\* `data_warehouse` - data_warehouse\n\* `data_warehouse_person_property` - data_warehouse_person_property\n\* `error_tracking_issue` - error_tracking_issue\n\* `log` - log\n\* `log_attribute` - log_attribute\n\* `log_resource_attribute` - log_resource_attribute\n\* `metric_attribute` - metric_attribute\n\* `span` - span\n\* `span_attribute` - span_attribute\n\* `span_resource_attribute` - span_resource_attribute\n\* `revenue_analytics` - revenue_analytics\n\* `account_custom_property` - account_custom_property\n\* `flag` - flag\n\* `workflow_variable` - workflow_variable'
        ),
        operator: ExistenceOperatorEnumApi.describe(
            'Existence check operator.\n\n\* `is_set` - is_set\n\* `is_not_set` - is_not_set'
        ),
    })
    .describe('Checks whether a property is set or not, without comparing values.')

export type ExistencePropertyFilterApi = zod.input<typeof ExistencePropertyFilterApi>
export type ExistencePropertyFilterApiOutput = zod.output<typeof ExistencePropertyFilterApi>

export const ActionStepPropertyFilterApi = zod.union([
    StringPropertyFilterApi,
    NumericPropertyFilterApi,
    ArrayPropertyFilterApi,
    DatePropertyFilterApi,
    ExistencePropertyFilterApi,
])

export type ActionStepPropertyFilterApi = zod.input<typeof ActionStepPropertyFilterApi>
export type ActionStepPropertyFilterApiOutput = zod.output<typeof ActionStepPropertyFilterApi>

export const ActionStepMatchingEnumApi = zod
    .enum(['contains', 'regex', 'exact'])
    .describe('\* `contains` - contains\n\* `regex` - regex\n\* `exact` - exact')

export type ActionStepMatchingEnumApi = zod.input<typeof ActionStepMatchingEnumApi>
export type ActionStepMatchingEnumApiOutput = zod.output<typeof ActionStepMatchingEnumApi>

export const ActionStepJSONApi = zod.object({
    event: zod
        .string()
        .nullish()
        .describe("Event name to match (e.g. '$pageview', '$autocapture', or a custom event name)."),
    properties: zod
        .array(ActionStepPropertyFilterApi)
        .nullish()
        .describe(
            "Event or person property filters. Each item should have 'key' (string), 'value' (string, number, boolean, or array), optional 'operator' (exact, is_not, is_set, is_not_set, icontains, not_icontains, regex, not_regex, gt, gte, lt, lte), and optional 'type' (event, person)."
        ),
    selector: zod.string().nullish().describe("CSS selector to match the target element (e.g. 'div > button.cta')."),
    selector_regex: zod.string().nullable(),
    tag_name: zod.string().nullish().describe('HTML tag name to match (e.g. \"button\", \"a\", \"input\").'),
    text: zod.string().nullish().describe('Element text content to match.'),
    text_matching: zod
        .union([ActionStepMatchingEnumApi, zod.null()])
        .optional()
        .describe(
            'How to match the text value. Defaults to exact.\n\n\* `contains` - contains\n\* `regex` - regex\n\* `exact` - exact'
        ),
    href: zod.string().nullish().describe('Link href attribute to match.'),
    href_matching: zod
        .union([ActionStepMatchingEnumApi, zod.null()])
        .optional()
        .describe(
            'How to match the href value. Defaults to exact.\n\n\* `contains` - contains\n\* `regex` - regex\n\* `exact` - exact'
        ),
    url: zod.string().nullish().describe('Page URL to match.'),
    url_matching: zod
        .union([ActionStepMatchingEnumApi, zod.null()])
        .optional()
        .describe(
            'How to match the URL value. Defaults to contains.\n\n\* `contains` - contains\n\* `regex` - regex\n\* `exact` - exact'
        ),
})

export type ActionStepJSONApi = zod.input<typeof ActionStepJSONApi>
export type ActionStepJSONApiOutput = zod.output<typeof ActionStepJSONApi>

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

export const actionApiNameMax = 400

export const actionApiSlackMessageFormatMax = 1200

export const actionApiIsActionDefault = true

export const ActionApi = zod
    .object({
        id: zod.number(),
        name: zod
            .string()
            .max(actionApiNameMax)
            .nullish()
            .describe('Name of the action (must be unique within the project).'),
        description: zod.string().optional().describe('Human-readable description of what this action represents.'),
        tags: zod.array(zod.unknown()).optional(),
        post_to_slack: zod
            .boolean()
            .optional()
            .describe('Whether to post a notification to Slack when this action is triggered.'),
        slack_message_format: zod
            .string()
            .max(actionApiSlackMessageFormatMax)
            .optional()
            .describe('Custom Slack message format. Supports templates with event properties.'),
        steps: zod
            .array(ActionStepJSONApi)
            .optional()
            .describe(
                'Action steps defining trigger conditions. Each step matches events by name, properties, URL, or element attributes. Multiple steps are OR-ed together.'
            ),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: UserBasicApi,
        deleted: zod.boolean().optional(),
        is_calculating: zod.boolean(),
        last_calculated_at: zod.iso.datetime({ offset: true }).optional(),
        team_id: zod.number(),
        is_action: zod.boolean().default(actionApiIsActionDefault),
        bytecode_error: zod.string().nullable(),
        pinned_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe(
                'ISO 8601 timestamp when the action was pinned, or null if not pinned. Set any value to pin, null to unpin.'
            ),
        creation_context: zod.string().nullable(),
        _create_in_folder: zod.string().optional(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('Serializer mixin that handles tags for objects.')

export type ActionApi = zod.input<typeof ActionApi>
export type ActionApiOutput = zod.output<typeof ActionApi>

export const PaginatedActionListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ActionApi),
})

export type PaginatedActionListApi = zod.input<typeof PaginatedActionListApi>
export type PaginatedActionListApiOutput = zod.output<typeof PaginatedActionListApi>

export const patchedActionApiNameMax = 400

export const patchedActionApiSlackMessageFormatMax = 1200

export const patchedActionApiIsActionDefault = true

export const PatchedActionApi = zod
    .object({
        id: zod.number().optional(),
        name: zod
            .string()
            .max(patchedActionApiNameMax)
            .nullish()
            .describe('Name of the action (must be unique within the project).'),
        description: zod.string().optional().describe('Human-readable description of what this action represents.'),
        tags: zod.array(zod.unknown()).optional(),
        post_to_slack: zod
            .boolean()
            .optional()
            .describe('Whether to post a notification to Slack when this action is triggered.'),
        slack_message_format: zod
            .string()
            .max(patchedActionApiSlackMessageFormatMax)
            .optional()
            .describe('Custom Slack message format. Supports templates with event properties.'),
        steps: zod
            .array(ActionStepJSONApi)
            .optional()
            .describe(
                'Action steps defining trigger conditions. Each step matches events by name, properties, URL, or element attributes. Multiple steps are OR-ed together.'
            ),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        created_by: UserBasicApi.optional(),
        deleted: zod.boolean().optional(),
        is_calculating: zod.boolean().optional(),
        last_calculated_at: zod.iso.datetime({ offset: true }).optional(),
        team_id: zod.number().optional(),
        is_action: zod.boolean().default(patchedActionApiIsActionDefault),
        bytecode_error: zod.string().nullish(),
        pinned_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe(
                'ISO 8601 timestamp when the action was pinned, or null if not pinned. Set any value to pin, null to unpin.'
            ),
        creation_context: zod.string().nullish(),
        _create_in_folder: zod.string().optional(),
        user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
    })
    .describe('Serializer mixin that handles tags for objects.')

export type PatchedActionApi = zod.input<typeof PatchedActionApi>
export type PatchedActionApiOutput = zod.output<typeof PatchedActionApi>

export const ActionReferenceApi = zod.object({
    type: zod.string().describe('Resource type: insight, experiment, cohort, or hog_function'),
    id: zod.string().describe('Resource ID (integer or UUID depending on type)'),
    name: zod.string().describe('Resource name'),
    url: zod.string().describe('Relative URL to the resource'),
    created_at: zod.iso.datetime({ offset: true }).nullable().describe('When the resource was created'),
    created_by: zod.union([UserBasicApi, zod.null()]).describe('User who created the resource'),
})

export type ActionReferenceApi = zod.input<typeof ActionReferenceApi>
export type ActionReferenceApiOutput = zod.output<typeof ActionReferenceApi>

export const BulkUpdateTagsActionEnumApi = zod
    .enum(['add', 'remove', 'set'])
    .describe('\* `add` - add\n\* `remove` - remove\n\* `set` - set')

export type BulkUpdateTagsActionEnumApi = zod.input<typeof BulkUpdateTagsActionEnumApi>
export type BulkUpdateTagsActionEnumApiOutput = zod.output<typeof BulkUpdateTagsActionEnumApi>

export const bulkUpdateTagsRequestApiIdsMax = 500

export const BulkUpdateTagsRequestApi = zod.object({
    ids: zod.array(zod.number()).max(bulkUpdateTagsRequestApiIdsMax).describe('List of object IDs to update tags on.'),
    action: BulkUpdateTagsActionEnumApi.describe(
        "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n\* `add` - add\n\* `remove` - remove\n\* `set` - set"
    ),
    tags: zod.array(zod.string()).describe('Tag names to add, remove, or set.'),
})

export type BulkUpdateTagsRequestApi = zod.input<typeof BulkUpdateTagsRequestApi>
export type BulkUpdateTagsRequestApiOutput = zod.output<typeof BulkUpdateTagsRequestApi>

export const BulkUpdateTagsItemApi = zod.object({
    id: zod.number(),
    tags: zod.array(zod.string()),
})

export type BulkUpdateTagsItemApi = zod.input<typeof BulkUpdateTagsItemApi>
export type BulkUpdateTagsItemApiOutput = zod.output<typeof BulkUpdateTagsItemApi>

export const BulkUpdateTagsErrorApi = zod.object({
    id: zod.number(),
    reason: zod.string(),
})

export type BulkUpdateTagsErrorApi = zod.input<typeof BulkUpdateTagsErrorApi>
export type BulkUpdateTagsErrorApiOutput = zod.output<typeof BulkUpdateTagsErrorApi>

export const BulkUpdateTagsResponseApi = zod.object({
    updated: zod.array(BulkUpdateTagsItemApi),
    skipped: zod.array(BulkUpdateTagsErrorApi),
})

export type BulkUpdateTagsResponseApi = zod.input<typeof BulkUpdateTagsResponseApi>
export type BulkUpdateTagsResponseApiOutput = zod.output<typeof BulkUpdateTagsResponseApi>
