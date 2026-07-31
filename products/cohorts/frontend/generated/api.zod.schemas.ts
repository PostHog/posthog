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

export const StaffCohortApi = zod.object({
    id: zod.number().describe('Cohort id.'),
    name: zod.string().nullable().describe('Cohort name.'),
    team_id: zod.number().describe('Id of the team the cohort belongs to.'),
    team_name: zod.string().describe('Name of the team the cohort belongs to.'),
    project_id: zod
        .number()
        .describe("Project id the cohort's team belongs to, for building \/project\/<id>\/cohorts\/<id> links."),
    deleted: zod.boolean().describe('Whether the cohort is soft-deleted.'),
    is_static: zod
        .boolean()
        .describe('Whether the cohort is static (populated once from a source rather than recalculated).'),
    is_calculating: zod.boolean().describe('Whether a calculation is currently marked as in flight.'),
    last_calculation: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the last calculation completed, or null if never calculated.'),
    last_calculation_duration_ms: zod
        .number()
        .nullable()
        .describe('Duration of the last completed calculation in milliseconds.'),
    errors_calculating: zod
        .number()
        .describe('Consecutive calculation failures; above 20 the cohort is excluded from periodic recalculation.'),
    last_error_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the last calculation error was recorded.'),
    version: zod.number().nullable().describe('Version of the last completed calculation.'),
    pending_version: zod
        .number()
        .nullable()
        .describe('Version most recently requested; greater than `version` while a calculation is pending or stuck.'),
    count: zod.number().nullable().describe('Number of persons in the cohort as of the last completed calculation.'),
    created_at: zod.iso.datetime({ offset: true }).nullable().describe('When the cohort was created.'),
})

export type StaffCohortApi = zod.input<typeof StaffCohortApi>
export type StaffCohortApiOutput = zod.output<typeof StaffCohortApi>

export const StaffCohortLookupResponseApi = zod.object({
    results: zod.array(StaffCohortApi).describe('Requested cohorts, in request order.'),
    not_found_cohort_ids: zod.array(zod.number()).describe('Requested cohort ids that do not exist.'),
})

export type StaffCohortLookupResponseApi = zod.input<typeof StaffCohortLookupResponseApi>
export type StaffCohortLookupResponseApiOutput = zod.output<typeof StaffCohortLookupResponseApi>

export const staffCohortRecalculateApiCohortIdsMax = 10

export const StaffCohortRecalculateApi = zod.object({
    cohort_ids: zod
        .array(zod.number())
        .min(1)
        .max(staffCohortRecalculateApiCohortIdsMax)
        .describe('Cohort ids to force-recalculate (max 10 per request).'),
})

export type StaffCohortRecalculateApi = zod.input<typeof StaffCohortRecalculateApi>
export type StaffCohortRecalculateApiOutput = zod.output<typeof StaffCohortRecalculateApi>

export const StaffCohortFailedApi = zod.object({
    cohort_id: zod.number().describe('Cohort id that raised while being enqueued.'),
    error: zod.string().describe('Error message from the failed enqueue attempt.'),
})

export type StaffCohortFailedApi = zod.input<typeof StaffCohortFailedApi>
export type StaffCohortFailedApiOutput = zod.output<typeof StaffCohortFailedApi>

export const StaffCohortSkippedApi = zod.object({
    cohort_id: zod.number().describe('Cohort id that was skipped.'),
    reason: zod.string().describe('Why the cohort was not enqueued for recalculation.'),
})

export type StaffCohortSkippedApi = zod.input<typeof StaffCohortSkippedApi>
export type StaffCohortSkippedApiOutput = zod.output<typeof StaffCohortSkippedApi>

export const StaffCohortRecalculateResponseApi = zod.object({
    queued_cohort_ids: zod
        .array(zod.number())
        .describe('Cohort ids for which a recalculation was enqueued (including their dependency chains).'),
    partial_cohort_ids: zod
        .array(zod.number())
        .describe(
            'Subset of queued_cohort_ids whose dependency chain failed to resolve, so only the cohort itself (not its dependents\/dependencies) was enqueued. Those related cohorts are still stale; re-request recalculation for them explicitly once the dependency issue is fixed.'
        ),
    failed_cohort_ids: zod
        .array(StaffCohortFailedApi)
        .describe(
            'Cohort ids that raised while being enqueued and were not queued at all. Cohorts listed elsewhere in this response already had their enqueue attempted; retry only these ids rather than the whole batch.'
        ),
    skipped: zod.array(StaffCohortSkippedApi).describe('Cohorts that exist but were not enqueued, with the reason.'),
    not_found_cohort_ids: zod.array(zod.number()).describe('Requested cohort ids that do not exist.'),
})

export type StaffCohortRecalculateResponseApi = zod.input<typeof StaffCohortRecalculateResponseApi>
export type StaffCohortRecalculateResponseApiOutput = zod.output<typeof StaffCohortRecalculateResponseApi>

export const StaffStuckCohortsResponseApi = zod.object({
    results: zod.array(StaffCohortApi).describe('Stuck cohorts, oldest last_calculation first (max 100).'),
    total_count: zod.number().describe('Total number of stuck cohorts instance-wide.'),
})

export type StaffStuckCohortsResponseApi = zod.input<typeof StaffStuckCohortsResponseApi>
export type StaffStuckCohortsResponseApiOutput = zod.output<typeof StaffStuckCohortsResponseApi>

export const CohortFilterGroupApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type CohortFilterGroupApi = zod.input<typeof CohortFilterGroupApi>
export type CohortFilterGroupApiOutput = zod.output<typeof CohortFilterGroupApi>

export const CohortFiltersApi = zod.object({
    properties: CohortFilterGroupApi,
    filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
})

export type CohortFiltersApi = zod.input<typeof CohortFiltersApi>
export type CohortFiltersApiOutput = zod.output<typeof CohortFiltersApi>

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

export const CohortTypeEnumApi = zod
    .enum(['static', 'person_property', 'behavioral', 'realtime', 'analytical'])
    .describe(
        '\* `static` - static\n\* `person_property` - person_property\n\* `behavioral` - behavioral\n\* `realtime` - realtime\n\* `analytical` - analytical'
    )

export type CohortTypeEnumApi = zod.input<typeof CohortTypeEnumApi>
export type CohortTypeEnumApiOutput = zod.output<typeof CohortTypeEnumApi>

export const CohortConditionTypeFlagsApi = zod.object({
    person_properties: zod.boolean().describe('The filters include a person property or person_metadata condition.'),
    behavioral: zod
        .boolean()
        .describe(
            'The filters include a behavioral condition that is not lifecycle-style (e.g. performed_event, performed_event_multiple, performed_event_sequence, or their negations).'
        ),
    lifecycle: zod
        .boolean()
        .describe(
            'The filters include a lifecycle-style behavioral condition (first-seen\/regularly\/stopped\/restarted performing an event).'
        ),
    cohorts: zod.boolean().describe('The filters include a nested reference to another cohort.'),
})

export type CohortConditionTypeFlagsApi = zod.input<typeof CohortConditionTypeFlagsApi>
export type CohortConditionTypeFlagsApiOutput = zod.output<typeof CohortConditionTypeFlagsApi>

export const SearchMatchTypeEnumApi = zod.enum(['exact', 'similar'])

export type SearchMatchTypeEnumApi = zod.input<typeof SearchMatchTypeEnumApi>
export type SearchMatchTypeEnumApiOutput = zod.output<typeof SearchMatchTypeEnumApi>

export const cohortApiNameMax = 400

export const cohortApiDescriptionMax = 1000

export const cohortApiCreateStaticPersonIdsDefault = []

export const CohortApi = zod.object({
    id: zod.number(),
    name: zod.string().max(cohortApiNameMax).nullish(),
    description: zod.string().max(cohortApiDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod.union([CohortFiltersApi, zod.null()]).optional(),
    query: zod.unknown().optional(),
    version: zod.number().nullable(),
    pending_version: zod.number().nullable(),
    is_calculating: zod.boolean(),
    created_by: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }).nullable(),
    last_calculation: zod.iso.datetime({ offset: true }).nullable(),
    last_backfill_person_properties_at: zod.iso.datetime({ offset: true }).nullable(),
    errors_calculating: zod.number(),
    last_error_message: zod.string().nullable(),
    count: zod.number().nullable(),
    is_static: zod.boolean().optional(),
    cohort_type: zod
        .union([CohortTypeEnumApi, BlankEnumApi, zod.null()])
        .optional()
        .describe(
            'Type of cohort based on filter complexity\n\n\* `static` - static\n\* `person_property` - person_property\n\* `behavioral` - behavioral\n\* `realtime` - realtime\n\* `analytical` - analytical'
        ),
    condition_type: zod
        .union([CohortConditionTypeFlagsApi, zod.null()])
        .describe(
            "Flags describing which kinds of conditions the cohort's filters contain. Null when the cohort has no filters to classify."
        ),
    experiment_set: zod.array(zod.number()),
    search_match_type: zod
        .union([SearchMatchTypeEnumApi, zod.null()])
        .describe(
            'How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`.'
        ),
    _create_in_folder: zod.string().optional(),
    _create_static_person_ids: zod.array(zod.string()).default(cohortApiCreateStaticPersonIdsDefault),
})

export type CohortApi = zod.input<typeof CohortApi>
export type CohortApiOutput = zod.output<typeof CohortApi>

export const PaginatedCohortListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(CohortApi),
})

export type PaginatedCohortListApi = zod.input<typeof PaginatedCohortListApi>
export type PaginatedCohortListApiOutput = zod.output<typeof PaginatedCohortListApi>

export const patchedCohortApiNameMax = 400

export const patchedCohortApiDescriptionMax = 1000

export const patchedCohortApiCreateStaticPersonIdsDefault = []

export const PatchedCohortApi = zod.object({
    id: zod.number().optional(),
    name: zod.string().max(patchedCohortApiNameMax).nullish(),
    description: zod.string().max(patchedCohortApiDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod.union([CohortFiltersApi, zod.null()]).optional(),
    query: zod.unknown().optional(),
    version: zod.number().nullish(),
    pending_version: zod.number().nullish(),
    is_calculating: zod.boolean().optional(),
    created_by: UserBasicApi.optional(),
    created_at: zod.iso.datetime({ offset: true }).nullish(),
    last_calculation: zod.iso.datetime({ offset: true }).nullish(),
    last_backfill_person_properties_at: zod.iso.datetime({ offset: true }).nullish(),
    errors_calculating: zod.number().optional(),
    last_error_message: zod.string().nullish(),
    count: zod.number().nullish(),
    is_static: zod.boolean().optional(),
    cohort_type: zod
        .union([CohortTypeEnumApi, BlankEnumApi, zod.null()])
        .optional()
        .describe(
            'Type of cohort based on filter complexity\n\n\* `static` - static\n\* `person_property` - person_property\n\* `behavioral` - behavioral\n\* `realtime` - realtime\n\* `analytical` - analytical'
        ),
    condition_type: zod
        .union([CohortConditionTypeFlagsApi, zod.null()])
        .optional()
        .describe(
            "Flags describing which kinds of conditions the cohort's filters contain. Null when the cohort has no filters to classify."
        ),
    experiment_set: zod.array(zod.number()).optional(),
    search_match_type: zod
        .union([SearchMatchTypeEnumApi, zod.null()])
        .optional()
        .describe(
            'How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`.'
        ),
    _create_in_folder: zod.string().optional(),
    _create_static_person_ids: zod.array(zod.string()).default(patchedCohortApiCreateStaticPersonIdsDefault),
})

export type PatchedCohortApi = zod.input<typeof PatchedCohortApi>
export type PatchedCohortApiOutput = zod.output<typeof PatchedCohortApi>

export const PatchedAddPersonsToStaticCohortRequestApi = zod.object({
    person_ids: zod.array(zod.uuid()).optional().describe('List of person UUIDs to add to the cohort'),
})

export type PatchedAddPersonsToStaticCohortRequestApi = zod.input<typeof PatchedAddPersonsToStaticCohortRequestApi>
export type PatchedAddPersonsToStaticCohortRequestApiOutput = zod.output<
    typeof PatchedAddPersonsToStaticCohortRequestApi
>

export const CohortPersonResultTypeEnumApi = zod.enum(['person']).describe('\* `person` - person')

export type CohortPersonResultTypeEnumApi = zod.input<typeof CohortPersonResultTypeEnumApi>
export type CohortPersonResultTypeEnumApiOutput = zod.output<typeof CohortPersonResultTypeEnumApi>

export const CohortPersonResultApi = zod.object({
    id: zod.string(),
    uuid: zod.uuid(),
    type: CohortPersonResultTypeEnumApi,
    name: zod.string(),
    distinct_ids: zod.array(zod.string()),
    properties: zod.record(zod.string(), zod.unknown()),
    created_at: zod.iso.datetime({ offset: true }).nullable(),
    last_seen_at: zod.iso.datetime({ offset: true }).nullable(),
    is_identified: zod.boolean().nullable(),
    matched_recordings: zod.array(zod.record(zod.string(), zod.unknown())),
    value_at_data_point: zod.number().nullable(),
})

export type CohortPersonResultApi = zod.input<typeof CohortPersonResultApi>
export type CohortPersonResultApiOutput = zod.output<typeof CohortPersonResultApi>

export const CohortPersonsResponseApi = zod.object({
    results: zod.array(CohortPersonResultApi),
    next: zod.url().nullable(),
    previous: zod.url().nullable(),
})

export type CohortPersonsResponseApi = zod.input<typeof CohortPersonsResponseApi>
export type CohortPersonsResponseApiOutput = zod.output<typeof CohortPersonsResponseApi>

export const PatchedRemovePersonRequestApi = zod.object({
    person_id: zod.uuid().optional().describe('Person UUID to remove from the cohort'),
})

export type PatchedRemovePersonRequestApi = zod.input<typeof PatchedRemovePersonRequestApi>
export type PatchedRemovePersonRequestApiOutput = zod.output<typeof PatchedRemovePersonRequestApi>

export const CohortUsedInFlagApi = zod.object({
    id: zod.number().describe('Feature flag database ID'),
    key: zod.string().describe('Feature flag key (URL slug)'),
    name: zod.string().nullable().describe('Feature flag display name'),
})

export type CohortUsedInFlagApi = zod.input<typeof CohortUsedInFlagApi>
export type CohortUsedInFlagApiOutput = zod.output<typeof CohortUsedInFlagApi>

export const CohortUsedInFlagsBlockApi = zod.object({
    results: zod.array(CohortUsedInFlagApi).describe('Feature flags referencing this cohort, capped at 100 results'),
    total: zod.number().describe('Total number of feature flags referencing this cohort, before truncation'),
    has_more: zod.boolean().describe('True when more feature flags exist beyond the truncation cap'),
})

export type CohortUsedInFlagsBlockApi = zod.input<typeof CohortUsedInFlagsBlockApi>
export type CohortUsedInFlagsBlockApiOutput = zod.output<typeof CohortUsedInFlagsBlockApi>

export const CohortUsedInInsightApi = zod.object({
    id: zod.number().describe('Insight database ID'),
    short_id: zod.string().describe('Insight short ID used for routing in the frontend'),
    name: zod
        .string()
        .describe("Insight display name; falls back to derived name, then to 'Unnamed' when both are empty"),
})

export type CohortUsedInInsightApi = zod.input<typeof CohortUsedInInsightApi>
export type CohortUsedInInsightApiOutput = zod.output<typeof CohortUsedInInsightApi>

export const CohortUsedInInsightsBlockApi = zod.object({
    results: zod.array(CohortUsedInInsightApi).describe('Insights referencing this cohort, capped at 100 results'),
    total: zod.number().describe('Total number of insights referencing this cohort, before truncation'),
    has_more: zod.boolean().describe('True when more insights exist beyond the truncation cap'),
})

export type CohortUsedInInsightsBlockApi = zod.input<typeof CohortUsedInInsightsBlockApi>
export type CohortUsedInInsightsBlockApiOutput = zod.output<typeof CohortUsedInInsightsBlockApi>

export const CohortUsedInCohortApi = zod.object({
    id: zod.number().describe('Cohort database ID'),
    name: zod.string().describe("Cohort display name; falls back to 'Unnamed' when empty"),
})

export type CohortUsedInCohortApi = zod.input<typeof CohortUsedInCohortApi>
export type CohortUsedInCohortApiOutput = zod.output<typeof CohortUsedInCohortApi>

export const CohortUsedInCohortsBlockApi = zod.object({
    results: zod
        .array(CohortUsedInCohortApi)
        .describe('Cohorts that include this cohort as a criterion, capped at 100 results'),
    total: zod.number().describe('Total number of cohorts referencing this cohort, before truncation'),
    has_more: zod.boolean().describe('True when more cohorts exist beyond the truncation cap'),
})

export type CohortUsedInCohortsBlockApi = zod.input<typeof CohortUsedInCohortsBlockApi>
export type CohortUsedInCohortsBlockApiOutput = zod.output<typeof CohortUsedInCohortsBlockApi>

export const CohortUsedInResponseApi = zod.object({
    feature_flags: CohortUsedInFlagsBlockApi.describe(
        'Feature flags (active and inactive, excluding soft-deleted) that reference this cohort in their targeting conditions, with truncation metadata'
    ),
    insights: CohortUsedInInsightsBlockApi.describe('Insights referencing this cohort with truncation metadata'),
    cohorts: CohortUsedInCohortsBlockApi.describe(
        'Other cohorts that include this cohort as a criterion, with truncation metadata'
    ),
})

export type CohortUsedInResponseApi = zod.input<typeof CohortUsedInResponseApi>
export type CohortUsedInResponseApiOutput = zod.output<typeof CohortUsedInResponseApi>

export const PropertyGroupOperatorApi = zod.enum(['AND', 'OR'])

export type PropertyGroupOperatorApi = zod.input<typeof PropertyGroupOperatorApi>
export type PropertyGroupOperatorApiOutput = zod.output<typeof PropertyGroupOperatorApi>

export const EventPropFilterTypeEnumApi = zod.enum(['event', 'element'])

export type EventPropFilterTypeEnumApi = zod.input<typeof EventPropFilterTypeEnumApi>
export type EventPropFilterTypeEnumApiOutput = zod.output<typeof EventPropFilterTypeEnumApi>

export const EventPropFilterApi = zod.object({
    type: EventPropFilterTypeEnumApi,
    key: zod.string(),
    value: zod.unknown(),
    operator: zod.union([zod.string(), zod.null()]).optional(),
})

export type EventPropFilterApi = zod.input<typeof EventPropFilterApi>
export type EventPropFilterApiOutput = zod.output<typeof EventPropFilterApi>

export const HogQLFilterApi = zod.object({
    type: zod.literal('hogql'),
    key: zod.string(),
    value: zod.unknown().optional(),
})

export type HogQLFilterApi = zod.input<typeof HogQLFilterApi>
export type HogQLFilterApiOutput = zod.output<typeof HogQLFilterApi>

export const behavioralFilterApiNegationDefault = false

export const BehavioralFilterApi = zod.object({
    bytecode: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    bytecode_error: zod.union([zod.string(), zod.null()]).optional(),
    conditionHash: zod.union([zod.string(), zod.null()]).optional(),
    type: zod.literal('behavioral'),
    key: zod.union([zod.string(), zod.number()]),
    value: zod.string(),
    event_type: zod.string(),
    time_value: zod.union([zod.number(), zod.null()]).optional(),
    time_interval: zod.union([zod.string(), zod.null()]).optional(),
    negation: zod.boolean().default(behavioralFilterApiNegationDefault),
    operator: zod.union([zod.string(), zod.null()]).optional(),
    operator_value: zod.union([zod.number(), zod.null()]).optional(),
    seq_time_interval: zod.union([zod.string(), zod.null()]).optional(),
    seq_time_value: zod.union([zod.number(), zod.null()]).optional(),
    seq_event: zod.union([zod.string(), zod.number(), zod.null()]).optional(),
    seq_event_type: zod.union([zod.string(), zod.null()]).optional(),
    total_periods: zod.union([zod.number(), zod.null()]).optional(),
    min_periods: zod.union([zod.number(), zod.null()]).optional(),
    event_filters: zod.union([zod.array(zod.union([EventPropFilterApi, HogQLFilterApi])), zod.null()]).optional(),
    explicit_datetime: zod.union([zod.string(), zod.null()]).optional(),
    explicit_datetime_to: zod.union([zod.string(), zod.null()]).optional(),
})

export type BehavioralFilterApi = zod.input<typeof BehavioralFilterApi>
export type BehavioralFilterApiOutput = zod.output<typeof BehavioralFilterApi>

export const cohortFilterApiNegationDefault = false

export const CohortFilterApi = zod.object({
    bytecode: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    bytecode_error: zod.union([zod.string(), zod.null()]).optional(),
    conditionHash: zod.union([zod.string(), zod.null()]).optional(),
    type: zod.literal('cohort'),
    key: zod.literal('id'),
    value: zod.number(),
    negation: zod.boolean().default(cohortFilterApiNegationDefault),
})

export type CohortFilterApi = zod.input<typeof CohortFilterApi>
export type CohortFilterApiOutput = zod.output<typeof CohortFilterApi>

export const personFilterApiNegationDefault = false

export const PersonFilterApi = zod.object({
    operator: zod.union([zod.string(), zod.null()]).optional(),
    value: zod.unknown().optional(),
    bytecode: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    bytecode_error: zod.union([zod.string(), zod.null()]).optional(),
    conditionHash: zod.union([zod.string(), zod.null()]).optional(),
    type: zod.literal('person'),
    key: zod.string(),
    negation: zod.boolean().default(personFilterApiNegationDefault),
})

export type PersonFilterApi = zod.input<typeof PersonFilterApi>
export type PersonFilterApiOutput = zod.output<typeof PersonFilterApi>

export const personMetadataFilterApiNegationDefault = false

export const PersonMetadataFilterApi = zod
    .object({
        operator: zod.union([zod.string(), zod.null()]).optional(),
        value: zod.unknown().optional(),
        bytecode: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
        bytecode_error: zod.union([zod.string(), zod.null()]).optional(),
        conditionHash: zod.union([zod.string(), zod.null()]).optional(),
        type: zod.literal('person_metadata'),
        key: zod.string(),
        negation: zod.boolean().default(personMetadataFilterApiNegationDefault),
    })
    .describe(
        'Filter on a top-level persons-table column (e.g. created_at) rather than the\nproperties JSON. The matching key must be one of PERSON_METADATA_FIELDS.'
    )

export type PersonMetadataFilterApi = zod.input<typeof PersonMetadataFilterApi>
export type PersonMetadataFilterApiOutput = zod.output<typeof PersonMetadataFilterApi>
