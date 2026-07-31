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

export const DashboardTemplateScopeEnumApi = zod
    .enum(['team', 'organization', 'global', 'feature_flag'])
    .describe(
        '\* `team` - Only team\n\* `organization` - Organization\n\* `global` - Global\n\* `feature_flag` - Feature Flag'
    )

export type DashboardTemplateScopeEnumApi = zod.input<typeof DashboardTemplateScopeEnumApi>
export type DashboardTemplateScopeEnumApiOutput = zod.output<typeof DashboardTemplateScopeEnumApi>

export const NonPortableReferencesApi = zod.object({
    actions: zod
        .number()
        .describe(
            "Count of distinct action references in the template's tiles that are specific to the source project."
        ),
    cohorts: zod
        .number()
        .describe(
            "Count of distinct cohort references in the template's tiles that are specific to the source project."
        ),
    warehouse_tables: zod
        .array(zod.string())
        .describe(
            "Names of data warehouse tables referenced by the template's tiles that are specific to the source project."
        ),
})

export type NonPortableReferencesApi = zod.input<typeof NonPortableReferencesApi>
export type NonPortableReferencesApiOutput = zod.output<typeof NonPortableReferencesApi>

export const dashboardTemplateApiTemplateNameMax = 400

export const dashboardTemplateApiDashboardDescriptionMax = 400

export const dashboardTemplateApiTagsItemMax = 255

export const dashboardTemplateApiImageUrlMax = 8201

export const dashboardTemplateApiAvailabilityContextsItemMax = 255

export const DashboardTemplateApi = zod.object({
    id: zod.uuid(),
    template_name: zod.string().max(dashboardTemplateApiTemplateNameMax).nullish(),
    dashboard_description: zod.string().max(dashboardTemplateApiDashboardDescriptionMax).nullish(),
    dashboard_filters: zod.unknown().optional(),
    tags: zod.array(zod.string().max(dashboardTemplateApiTagsItemMax)).nullish(),
    tiles: zod.unknown().optional(),
    variables: zod.unknown().optional(),
    deleted: zod.boolean().nullish(),
    created_at: zod.iso.datetime({ offset: true }).nullable(),
    created_by: UserBasicApi,
    image_url: zod.string().max(dashboardTemplateApiImageUrlMax).nullish(),
    team_id: zod.number().nullable(),
    scope: zod.union([DashboardTemplateScopeEnumApi, BlankEnumApi, zod.null()]).optional(),
    availability_contexts: zod.array(zod.string().max(dashboardTemplateApiAvailabilityContextsItemMax)).nullish(),
    is_featured: zod.boolean().optional().describe('Manually curated; used to highlight templates in the UI.'),
    non_portable_references: NonPortableReferencesApi.describe(
        "Read-only. Project-specific references (actions, cohorts, data warehouse tables) embedded in this template's tiles that may not resolve when it is used in another project. Events and properties are matched by name and are portable, so they are not reported here."
    ),
})

export type DashboardTemplateApi = zod.input<typeof DashboardTemplateApi>
export type DashboardTemplateApiOutput = zod.output<typeof DashboardTemplateApi>

export const PaginatedDashboardTemplateListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(DashboardTemplateApi),
})

export type PaginatedDashboardTemplateListApi = zod.input<typeof PaginatedDashboardTemplateListApi>
export type PaginatedDashboardTemplateListApiOutput = zod.output<typeof PaginatedDashboardTemplateListApi>

export const patchedDashboardTemplateApiTemplateNameMax = 400

export const patchedDashboardTemplateApiDashboardDescriptionMax = 400

export const patchedDashboardTemplateApiTagsItemMax = 255

export const patchedDashboardTemplateApiImageUrlMax = 8201

export const patchedDashboardTemplateApiAvailabilityContextsItemMax = 255

export const PatchedDashboardTemplateApi = zod.object({
    id: zod.uuid().optional(),
    template_name: zod.string().max(patchedDashboardTemplateApiTemplateNameMax).nullish(),
    dashboard_description: zod.string().max(patchedDashboardTemplateApiDashboardDescriptionMax).nullish(),
    dashboard_filters: zod.unknown().optional(),
    tags: zod.array(zod.string().max(patchedDashboardTemplateApiTagsItemMax)).nullish(),
    tiles: zod.unknown().optional(),
    variables: zod.unknown().optional(),
    deleted: zod.boolean().nullish(),
    created_at: zod.iso.datetime({ offset: true }).nullish(),
    created_by: UserBasicApi.optional(),
    image_url: zod.string().max(patchedDashboardTemplateApiImageUrlMax).nullish(),
    team_id: zod.number().nullish(),
    scope: zod.union([DashboardTemplateScopeEnumApi, BlankEnumApi, zod.null()]).optional(),
    availability_contexts: zod
        .array(zod.string().max(patchedDashboardTemplateApiAvailabilityContextsItemMax))
        .nullish(),
    is_featured: zod.boolean().optional().describe('Manually curated; used to highlight templates in the UI.'),
    non_portable_references: NonPortableReferencesApi.optional().describe(
        "Read-only. Project-specific references (actions, cohorts, data warehouse tables) embedded in this template's tiles that may not resolve when it is used in another project. Events and properties are matched by name and are portable, so they are not reported here."
    ),
})

export type PatchedDashboardTemplateApi = zod.input<typeof PatchedDashboardTemplateApi>
export type PatchedDashboardTemplateApiOutput = zod.output<typeof PatchedDashboardTemplateApi>

export const CopyDashboardTemplateApi = zod.object({
    source_template_id: zod
        .uuid()
        .describe(
            'UUID of a team-scoped template in the same organization. Global and feature-flag templates cannot be copied with this endpoint.'
        ),
})

export type CopyDashboardTemplateApi = zod.input<typeof CopyDashboardTemplateApi>
export type CopyDashboardTemplateApiOutput = zod.output<typeof CopyDashboardTemplateApi>

export const CreationModeEnumApi = zod
    .enum(['default', 'template', 'duplicate', 'unlisted'])
    .describe(
        '\* `default` - Default\n\* `template` - Template\n\* `duplicate` - Duplicate\n\* `unlisted` - Unlisted (product-embedded)'
    )

export type CreationModeEnumApi = zod.input<typeof CreationModeEnumApi>
export type CreationModeEnumApiOutput = zod.output<typeof CreationModeEnumApi>

export const RestrictionLevelEnumApi = zod
    .union([zod.literal(21), zod.literal(37)])
    .describe('\* `21` - Everyone in the project can edit\n\* `37` - Only those invited to this dashboard can edit')

export type RestrictionLevelEnumApi = zod.input<typeof RestrictionLevelEnumApi>
export type RestrictionLevelEnumApiOutput = zod.output<typeof RestrictionLevelEnumApi>

export const EffectivePrivilegeLevelEnumApi = zod.union([zod.literal(21), zod.literal(37)])

export type EffectivePrivilegeLevelEnumApi = zod.input<typeof EffectivePrivilegeLevelEnumApi>
export type EffectivePrivilegeLevelEnumApiOutput = zod.output<typeof EffectivePrivilegeLevelEnumApi>

export const SearchMatchTypeEnumApi = zod.enum(['exact', 'similar'])

export type SearchMatchTypeEnumApi = zod.input<typeof SearchMatchTypeEnumApi>
export type SearchMatchTypeEnumApiOutput = zod.output<typeof SearchMatchTypeEnumApi>

export const DashboardBasicApi = zod
    .object({
        id: zod.number(),
        name: zod.string().nullable().describe('Name of the dashboard.'),
        description: zod.string().describe('Description of the dashboard.'),
        pinned: zod.boolean().describe('Whether the dashboard is pinned to the top of the list.'),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: UserBasicApi,
        last_accessed_at: zod.iso.datetime({ offset: true }).nullable(),
        last_viewed_at: zod.iso.datetime({ offset: true }).nullable(),
        folder: zod
            .string()
            .nullable()
            .describe(
                "Path of the project-tree folder this dashboard is filed under in the file system, e.g. 'Unfiled\/Dashboards'. An empty string means the project root; null means the dashboard has no file system entry. The dashboard's own name is not part of the path."
            ),
        is_shared: zod.boolean(),
        deleted: zod.boolean(),
        creation_mode: CreationModeEnumApi,
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: RestrictionLevelEnumApi.describe(
            'Controls who can edit the dashboard.\n\n\* `21` - Everyone in the project can edit\n\* `37` - Only those invited to this dashboard can edit'
        ),
        effective_restriction_level: EffectivePrivilegeLevelEnumApi,
        effective_privilege_level: EffectivePrivilegeLevelEnumApi,
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
        access_control_version: zod.string(),
        last_refresh: zod.iso.datetime({ offset: true }).nullable(),
        team_id: zod.number(),
        search_match_type: zod
            .union([SearchMatchTypeEnumApi, zod.null()])
            .describe(
                'How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`.'
            ),
    })
    .describe('Serializer mixin that handles tags for objects.')

export type DashboardBasicApi = zod.input<typeof DashboardBasicApi>
export type DashboardBasicApiOutput = zod.output<typeof DashboardBasicApi>

export const PaginatedDashboardBasicListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(DashboardBasicApi),
})

export type PaginatedDashboardBasicListApi = zod.input<typeof PaginatedDashboardBasicListApi>
export type PaginatedDashboardBasicListApiOutput = zod.output<typeof PaginatedDashboardBasicListApi>

export const dashboardApiNameMax = 400

export const dashboardApiDeleteInsightsDefault = false

export const DashboardApi = zod
    .object({
        id: zod.number(),
        name: zod.string().max(dashboardApiNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: UserBasicApi,
        last_accessed_at: zod.iso.datetime({ offset: true }).nullish(),
        last_viewed_at: zod.iso.datetime({ offset: true }).nullable(),
        folder: zod
            .string()
            .nullable()
            .describe(
                "Path of the project-tree folder this dashboard is filed under in the file system, e.g. 'Unfiled\/Dashboards'. An empty string means the project root; null means the dashboard has no file system entry. The dashboard's own name is not part of the path."
            ),
        is_shared: zod.boolean(),
        deleted: zod.boolean().optional(),
        creation_mode: CreationModeEnumApi,
        filters: zod.record(zod.string(), zod.unknown()),
        variables: zod.record(zod.string(), zod.unknown()).nullable(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: RestrictionLevelEnumApi.optional(),
        effective_restriction_level: EffectivePrivilegeLevelEnumApi,
        effective_privilege_level: EffectivePrivilegeLevelEnumApi,
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
        access_control_version: zod.string(),
        last_refresh: zod.iso.datetime({ offset: true }).nullish(),
        persisted_filters: zod.record(zod.string(), zod.unknown()).nullable(),
        persisted_variables: zod.record(zod.string(), zod.unknown()).nullable(),
        team_id: zod.number(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        tiles: zod.array(zod.record(zod.string(), zod.unknown())).nullable(),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardApiDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export type DashboardApi = zod.input<typeof DashboardApi>
export type DashboardApiOutput = zod.output<typeof DashboardApi>

export const DashboardCollaboratorApi = zod.object({
    id: zod.uuid(),
    dashboard_id: zod.number(),
    user: UserBasicApi,
    level: RestrictionLevelEnumApi,
    added_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    user_uuid: zod.uuid(),
})

export type DashboardCollaboratorApi = zod.input<typeof DashboardCollaboratorApi>
export type DashboardCollaboratorApiOutput = zod.output<typeof DashboardCollaboratorApi>

export const DashboardFiltersOpenApiApi = zod
    .object({
        date_from: zod
            .string()
            .nullish()
            .describe(
                "Dashboard-level start of the date range, e.g. '-30d', '-7d', or an ISO date. Applies to all tiles."
            ),
        date_to: zod
            .string()
            .nullish()
            .describe(
                "Dashboard-level end of the date range, e.g. '-1d' or an ISO date. Null\/omitted means up to now."
            ),
        properties: zod
            .unknown()
            .optional()
            .describe('Dashboard-level property filters applied to every tile (PostHog property filter group).'),
    })
    .describe(
        "OpenAPI-only shape for a dashboard's filters object (agents\/MCP).\n\nDocuments the dashboard-level filters that act as the single source of truth for the\ndashboard's tiles. Runtime persistence reads the raw ``filters`` dict from the request body, so\nextra keys are accepted, but these are the ones agents should set."
    )

export type DashboardFiltersOpenApiApi = zod.input<typeof DashboardFiltersOpenApiApi>
export type DashboardFiltersOpenApiApiOutput = zod.output<typeof DashboardFiltersOpenApiApi>

export const DashboardPatchWidgetOpenApiWidgetTypeEnumApi = zod
    .enum([
        'activity_events_list',
        'error_tracking_list',
        'experiment_results',
        'experiments_list',
        'logs_list',
        'session_replay_list',
        'survey_results',
    ])
    .describe(
        '\* `activity_events_list` - activity_events_list\n\* `error_tracking_list` - error_tracking_list\n\* `experiment_results` - experiment_results\n\* `experiments_list` - experiments_list\n\* `logs_list` - logs_list\n\* `session_replay_list` - session_replay_list\n\* `survey_results` - survey_results'
    )

export type DashboardPatchWidgetOpenApiWidgetTypeEnumApi = zod.input<
    typeof DashboardPatchWidgetOpenApiWidgetTypeEnumApi
>
export type DashboardPatchWidgetOpenApiWidgetTypeEnumApiOutput = zod.output<
    typeof DashboardPatchWidgetOpenApiWidgetTypeEnumApi
>

export const WidgetDateRangeApi = zod.object({
    date_from: zod
        .union([zod.enum(['-1M', '-30M', '-1h', '-3h', '-24h', '-7d', '-14d', '-30d', '-90d']), zod.null()])
        .optional(),
})

export type WidgetDateRangeApi = zod.input<typeof WidgetDateRangeApi>
export type WidgetDateRangeApiOutput = zod.output<typeof WidgetDateRangeApi>

export const PropertyOperatorApi = zod.enum([
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
    'gt',
    'gte',
    'lt',
    'lte',
    'is_set',
    'is_not_set',
    'is_date_exact',
    'is_date_before',
    'is_date_after',
    'between',
    'not_between',
    'min',
    'max',
    'in',
    'not_in',
    'is_cleaned_path_exact',
    'flag_evaluates_to',
    'semver_eq',
    'semver_neq',
    'semver_gt',
    'semver_gte',
    'semver_lt',
    'semver_lte',
    'semver_tilde',
    'semver_caret',
    'semver_wildcard',
    'icontains_multi',
    'not_icontains_multi',
])

export type PropertyOperatorApi = zod.input<typeof PropertyOperatorApi>
export type PropertyOperatorApiOutput = zod.output<typeof PropertyOperatorApi>

export const WidgetFilterEntryApi = zod.object({
    filterId: zod.string().min(1),
    propertyName: zod.string().min(1),
    optionId: zod.string().min(1),
    operator: PropertyOperatorApi,
    value: zod.union([zod.string(), zod.array(zod.string()), zod.null()]).optional(),
})

export type WidgetFilterEntryApi = zod.input<typeof WidgetFilterEntryApi>
export type WidgetFilterEntryApiOutput = zod.output<typeof WidgetFilterEntryApi>

export const activityEventsPropertyFilterApiKeyMax = 400

export const activityEventsPropertyFilterApiLabelOneMax = 400

export const activityEventsPropertyFilterApiValueOneItemOneMax = 4000

export const activityEventsPropertyFilterApiValueOneMax = 100

export const activityEventsPropertyFilterApiValueTwoMax = 4000

export const ActivityEventsPropertyFilterApi = zod.object({
    key: zod.string().min(1).max(activityEventsPropertyFilterApiKeyMax),
    label: zod.union([zod.string().max(activityEventsPropertyFilterApiLabelOneMax), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.enum(['event', 'person']),
    value: zod
        .union([
            zod
                .array(
                    zod.union([
                        zod.string().max(activityEventsPropertyFilterApiValueOneItemOneMax),
                        zod.number(),
                        zod.boolean(),
                    ])
                )
                .max(activityEventsPropertyFilterApiValueOneMax),
            zod.string().max(activityEventsPropertyFilterApiValueTwoMax),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type ActivityEventsPropertyFilterApi = zod.input<typeof ActivityEventsPropertyFilterApi>
export type ActivityEventsPropertyFilterApiOutput = zod.output<typeof ActivityEventsPropertyFilterApi>

export const activityEventsListWidgetConfigApiLimitDefault = 25
export const activityEventsListWidgetConfigApiLimitMax = 50

export const activityEventsListWidgetConfigApiPropertiesOneMax = 20

export const ActivityEventsListWidgetConfigApi = zod.object({
    dateRange: zod.union([WidgetDateRangeApi, zod.null()]).optional(),
    filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
    widgetFilters: zod.union([zod.record(zod.string(), WidgetFilterEntryApi), zod.null()]).optional(),
    limit: zod
        .number()
        .min(1)
        .max(activityEventsListWidgetConfigApiLimitMax)
        .default(activityEventsListWidgetConfigApiLimitDefault)
        .describe('Maximum number of events to return.'),
    eventName: zod
        .union([zod.string().min(1), zod.null()])
        .optional()
        .describe('Limit the feed to a single event name. Omit or null for all events.'),
    properties: zod
        .union([
            zod.array(ActivityEventsPropertyFilterApi).max(activityEventsListWidgetConfigApiPropertiesOneMax),
            zod.null(),
        ])
        .optional()
        .describe('Event and person property filters, matching Activity > Explore events.'),
})

export type ActivityEventsListWidgetConfigApi = zod.input<typeof ActivityEventsListWidgetConfigApi>
export type ActivityEventsListWidgetConfigApiOutput = zod.output<typeof ActivityEventsListWidgetConfigApi>

export const WidgetAssigneeFilterApi = zod.object({
    id: zod.union([zod.string(), zod.number()]),
    type: zod.enum(['user', 'role']),
})

export type WidgetAssigneeFilterApi = zod.input<typeof WidgetAssigneeFilterApi>
export type WidgetAssigneeFilterApiOutput = zod.output<typeof WidgetAssigneeFilterApi>

export const errorTrackingListWidgetConfigApiLimitDefault = 10
export const errorTrackingListWidgetConfigApiLimitMax = 25

export const errorTrackingListWidgetConfigApiOrderByDefault = `occurrences`
export const errorTrackingListWidgetConfigApiOrderDirectionDefault = `DESC`
export const errorTrackingListWidgetConfigApiStatusDefault = `active`

export const ErrorTrackingListWidgetConfigApi = zod.object({
    dateRange: zod.union([WidgetDateRangeApi, zod.null()]).optional(),
    filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
    widgetFilters: zod.union([zod.record(zod.string(), WidgetFilterEntryApi), zod.null()]).optional(),
    limit: zod
        .number()
        .min(1)
        .max(errorTrackingListWidgetConfigApiLimitMax)
        .default(errorTrackingListWidgetConfigApiLimitDefault)
        .describe('Maximum number of issues to return.'),
    orderBy: zod
        .enum(['last_seen', 'first_seen', 'occurrences', 'users', 'sessions'])
        .default(errorTrackingListWidgetConfigApiOrderByDefault)
        .describe('Issue ranking column.'),
    orderDirection: zod
        .enum(['ASC', 'DESC'])
        .default(errorTrackingListWidgetConfigApiOrderDirectionDefault)
        .describe('Sort direction for orderBy.'),
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed', 'all'])
        .default(errorTrackingListWidgetConfigApiStatusDefault)
        .describe('Issue status filter.'),
    assignee: zod
        .union([WidgetAssigneeFilterApi, zod.null()])
        .optional()
        .describe('Filter by assignee ({type: user|role, id}). Omit for any assignee.'),
})

export type ErrorTrackingListWidgetConfigApi = zod.input<typeof ErrorTrackingListWidgetConfigApi>
export type ErrorTrackingListWidgetConfigApiOutput = zod.output<typeof ErrorTrackingListWidgetConfigApi>

export const sessionReplayListWidgetConfigApiLimitDefault = 10
export const sessionReplayListWidgetConfigApiLimitMax = 25

export const sessionReplayListWidgetConfigApiOrderByDefault = `start_time`
export const sessionReplayListWidgetConfigApiOrderDirectionDefault = `DESC`

export const SessionReplayListWidgetConfigApi = zod.object({
    dateRange: zod.union([WidgetDateRangeApi, zod.null()]).optional(),
    filterTestAccounts: zod.union([zod.boolean(), zod.null()]).optional(),
    widgetFilters: zod.union([zod.record(zod.string(), WidgetFilterEntryApi), zod.null()]).optional(),
    limit: zod
        .number()
        .min(1)
        .max(sessionReplayListWidgetConfigApiLimitMax)
        .default(sessionReplayListWidgetConfigApiLimitDefault)
        .describe('Maximum number of recordings to return.'),
    orderBy: zod
        .enum(['start_time', 'activity_score', 'recording_duration', 'duration', 'click_count', 'console_error_count'])
        .default(sessionReplayListWidgetConfigApiOrderByDefault)
        .describe('Recording ranking column.'),
    orderDirection: zod
        .enum(['ASC', 'DESC'])
        .default(sessionReplayListWidgetConfigApiOrderDirectionDefault)
        .describe('Sort direction for orderBy.'),
    savedFilterId: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe(
            'short_id of a saved session replay filter to refine the recordings shown. When set, the saved filter owns the date range and property filters; only orderBy, orderDirection, and limit still apply. Combine with collectionId to filter within a collection.'
        ),
    collectionId: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe(
            'short_id of a session replay collection to scope the widget to its pinned recordings. Combine with savedFilterId or property filters to narrow within the collection; orderBy, orderDirection, and limit still apply.'
        ),
})

export type SessionReplayListWidgetConfigApi = zod.input<typeof SessionReplayListWidgetConfigApi>
export type SessionReplayListWidgetConfigApiOutput = zod.output<typeof SessionReplayListWidgetConfigApi>

export const experimentsListWidgetConfigApiLimitDefault = 10
export const experimentsListWidgetConfigApiLimitMax = 25

export const experimentsListWidgetConfigApiOrderByDefault = `created_at`
export const experimentsListWidgetConfigApiOrderDirectionDefault = `DESC`
export const experimentsListWidgetConfigApiStatusDefault = `all`

export const ExperimentsListWidgetConfigApi = zod.object({
    limit: zod
        .number()
        .min(1)
        .max(experimentsListWidgetConfigApiLimitMax)
        .default(experimentsListWidgetConfigApiLimitDefault)
        .describe('Maximum number of experiments to return.'),
    orderBy: zod
        .enum(['created_at', 'name', 'start_date'])
        .default(experimentsListWidgetConfigApiOrderByDefault)
        .describe('Experiment list sort column.'),
    orderDirection: zod
        .enum(['ASC', 'DESC'])
        .default(experimentsListWidgetConfigApiOrderDirectionDefault)
        .describe('Sort direction for orderBy.'),
    status: zod
        .enum(['draft', 'running', 'paused', 'exposure_frozen', 'stopped', 'all'])
        .default(experimentsListWidgetConfigApiStatusDefault)
        .describe('Experiment status filter.'),
    createdBy: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Filter by creator (user id). Omit for any creator.'),
})

export type ExperimentsListWidgetConfigApi = zod.input<typeof ExperimentsListWidgetConfigApi>
export type ExperimentsListWidgetConfigApiOutput = zod.output<typeof ExperimentsListWidgetConfigApi>

export const ExperimentResultsWidgetConfigApi = zod.object({
    experimentId: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Experiment to show results for. Null until the user picks one in the widget settings.'),
})

export type ExperimentResultsWidgetConfigApi = zod.input<typeof ExperimentResultsWidgetConfigApi>
export type ExperimentResultsWidgetConfigApiOutput = zod.output<typeof ExperimentResultsWidgetConfigApi>

export const surveyResultsWidgetConfigApiLimitDefault = 10
export const surveyResultsWidgetConfigApiLimitMax = 25

export const SurveyResultsWidgetConfigApi = zod.object({
    dateRange: zod
        .union([WidgetDateRangeApi, zod.null()])
        .optional()
        .describe("Null or omitted means all time (the survey's full lifetime)."),
    surveyId: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe('Survey to show performance stats and recent responses for. Null until the user picks one.'),
    limit: zod
        .number()
        .min(1)
        .max(surveyResultsWidgetConfigApiLimitMax)
        .default(surveyResultsWidgetConfigApiLimitDefault)
        .describe('Maximum number of recent responses to return.'),
})

export type SurveyResultsWidgetConfigApi = zod.input<typeof SurveyResultsWidgetConfigApi>
export type SurveyResultsWidgetConfigApiOutput = zod.output<typeof SurveyResultsWidgetConfigApi>

export const logsListWidgetConfigApiLimitDefault = 50
export const logsListWidgetConfigApiLimitMax = 100

export const logsListWidgetConfigApiOrderByDefault = `latest`
export const logsListWidgetConfigApiWrapLinesDefault = false
export const logsListWidgetConfigApiTimezoneDefault = `UTC`

export const LogsListWidgetConfigApi = zod.object({
    dateRange: zod.union([WidgetDateRangeApi, zod.null()]).optional(),
    limit: zod
        .number()
        .min(1)
        .max(logsListWidgetConfigApiLimitMax)
        .default(logsListWidgetConfigApiLimitDefault)
        .describe('Maximum number of log lines to return.'),
    orderBy: zod
        .enum(['latest', 'earliest'])
        .default(logsListWidgetConfigApiOrderByDefault)
        .describe('Sort by newest (latest) or oldest (earliest) first.'),
    severityLevels: zod
        .array(zod.enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal']))
        .optional()
        .describe('Only show logs at these severity levels. Empty shows all levels.'),
    serviceNames: zod
        .array(zod.string())
        .optional()
        .describe('Only show logs from these services. Empty shows all services.'),
    wrapLines: zod
        .boolean()
        .default(logsListWidgetConfigApiWrapLinesDefault)
        .describe('Wrap long log lines instead of truncating them to a single row.'),
    timezone: zod
        .enum(['UTC', 'local'])
        .default(logsListWidgetConfigApiTimezoneDefault)
        .describe("Render log timestamps in UTC or in each viewer's local timezone."),
    savedViewId: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe(
            'short_id of a saved logs view to use as the source. When set, the saved view owns the date range, severity, service, and property filters; only orderBy and limit still apply.'
        ),
})

export type LogsListWidgetConfigApi = zod.input<typeof LogsListWidgetConfigApi>
export type LogsListWidgetConfigApiOutput = zod.output<typeof LogsListWidgetConfigApi>

export const DashboardWidgetConfigApi = zod.union([
    ActivityEventsListWidgetConfigApi,
    ErrorTrackingListWidgetConfigApi,
    SessionReplayListWidgetConfigApi,
    ExperimentsListWidgetConfigApi,
    ExperimentResultsWidgetConfigApi,
    SurveyResultsWidgetConfigApi,
    LogsListWidgetConfigApi,
])

export type DashboardWidgetConfigApi = zod.input<typeof DashboardWidgetConfigApi>
export type DashboardWidgetConfigApiOutput = zod.output<typeof DashboardWidgetConfigApi>

export const dashboardPatchWidgetOpenApiApiNameMax = 400

export const DashboardPatchWidgetOpenApiApi = zod.object({
    id: zod.uuid().optional().describe('Existing widget row ID when updating a widget tile via dashboard PATCH.'),
    widget_type: DashboardPatchWidgetOpenApiWidgetTypeEnumApi.optional().describe(
        'Widget type identifier (cannot be changed on update).\n\n\* `activity_events_list` - activity_events_list\n\* `error_tracking_list` - error_tracking_list\n\* `experiment_results` - experiment_results\n\* `experiments_list` - experiments_list\n\* `logs_list` - logs_list\n\* `session_replay_list` - session_replay_list\n\* `survey_results` - survey_results'
    ),
    config: DashboardWidgetConfigApi.optional().describe(
        "Widget-specific configuration. Shape depends on the tile's widget_type."
    ),
    name: zod
        .string()
        .max(dashboardPatchWidgetOpenApiApiNameMax)
        .nullish()
        .describe('Optional custom display name for the widget tile.'),
    description: zod
        .string()
        .optional()
        .describe('Optional markdown description shown when show_description is enabled.'),
})

export type DashboardPatchWidgetOpenApiApi = zod.input<typeof DashboardPatchWidgetOpenApiApi>
export type DashboardPatchWidgetOpenApiApiOutput = zod.output<typeof DashboardPatchWidgetOpenApiApi>

export const DashboardPatchTileOpenApiApi = zod.object({
    id: zod.number().optional().describe('Dashboard tile ID to update.'),
    widget: DashboardPatchWidgetOpenApiApi.optional().describe('Nested widget row updates.'),
})

export type DashboardPatchTileOpenApiApi = zod.input<typeof DashboardPatchTileOpenApiApi>
export type DashboardPatchTileOpenApiApiOutput = zod.output<typeof DashboardPatchTileOpenApiApi>

export const patchedPatchedDashboardOpenApiApiNameMax = 400

export const patchedPatchedDashboardOpenApiApiDeleteInsightsDefault = false

export const PatchedPatchedDashboardOpenApiApi = zod
    .object({
        name: zod.string().max(patchedPatchedDashboardOpenApiApiNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        filters: DashboardFiltersOpenApiApi.optional().describe(
            'Dashboard-level filters (date range and properties) applied across all tiles as the source of truth.'
        ),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.string()).optional(),
        restriction_level: EffectivePrivilegeLevelEnumApi.optional(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard.'),
        tiles: zod
            .array(DashboardPatchTileOpenApiApi)
            .optional()
            .describe('Dashboard tiles to update. Widget tiles accept nested widget.config patches.'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(patchedPatchedDashboardOpenApiApiDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
    })
    .describe(
        'OpenAPI-only PATCH body for dashboards (agents\/MCP).\n\nMust be a superset of ``dashboard_patch_runtime_openapi_field_names()`` — ``extend_schema(request=...)``\nreplaces the inferred schema entirely. Contract: ``test_dashboard_openapi.py``.'
    )

export type PatchedPatchedDashboardOpenApiApi = zod.input<typeof PatchedPatchedDashboardOpenApiApi>
export type PatchedPatchedDashboardOpenApiApiOutput = zod.output<typeof PatchedPatchedDashboardOpenApiApi>

export const CopyDashboardTileRequestApi = zod.object({
    fromDashboardId: zod.number().describe('Dashboard id the tile currently belongs to.'),
    tileId: zod.number().describe('Dashboard tile id to copy.'),
})

export type CopyDashboardTileRequestApi = zod.input<typeof CopyDashboardTileRequestApi>
export type CopyDashboardTileRequestApiOutput = zod.output<typeof CopyDashboardTileRequestApi>

export const TileLayoutBoxApi = zod.object({
    x: zod.number().optional().describe('Column position in the dashboard grid (0-indexed).'),
    y: zod.number().optional().describe('Row position in the dashboard grid (0-indexed).'),
    w: zod.number().optional().describe('Width in grid columns. The desktop grid is 12 columns wide.'),
    h: zod.number().optional().describe('Height in grid rows.'),
})

export type TileLayoutBoxApi = zod.input<typeof TileLayoutBoxApi>
export type TileLayoutBoxApiOutput = zod.output<typeof TileLayoutBoxApi>

export const TileLayoutsApi = zod.object({
    sm: TileLayoutBoxApi.optional().describe(
        'Layout for the standard (desktop) breakpoint. The grid is 12 columns wide.'
    ),
    xs: TileLayoutBoxApi.optional().describe('Layout for the small (mobile) breakpoint. The grid is 1 column wide.'),
})

export type TileLayoutsApi = zod.input<typeof TileLayoutsApi>
export type TileLayoutsApiOutput = zod.output<typeof TileLayoutsApi>

export const createTextTileRequestApiBodyMax = 4000

export const createTextTileRequestApiColorMax = 400

export const CreateTextTileRequestApi = zod.object({
    body: zod
        .string()
        .min(1)
        .max(createTextTileRequestApiBodyMax)
        .describe(
            'Markdown body for the text tile. Supports headings, lists, and inline formatting. Useful as a dashboard section heading, divider, or annotation between insights. Max 4000 characters.'
        ),
    layouts: TileLayoutsApi.optional().describe(
        'Optional grid layout per breakpoint. If omitted, the tile is placed at the bottom of the dashboard using the default size. Text tiles typically use a thin full-width banner (e.g. w=12, h=1).'
    ),
    color: zod
        .string()
        .max(createTextTileRequestApiColorMax)
        .nullish()
        .describe("Optional accent color name (e.g. 'blue', 'green', 'purple', 'black')."),
})

export type CreateTextTileRequestApi = zod.input<typeof CreateTextTileRequestApi>
export type CreateTextTileRequestApiOutput = zod.output<typeof CreateTextTileRequestApi>

export const DashboardTileApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type DashboardTileApi = zod.input<typeof DashboardTileApi>
export type DashboardTileApiOutput = zod.output<typeof DashboardTileApi>

export const DeleteTileRequestApi = zod.object({
    tile_id: zod.number().describe('ID of the dashboard tile to delete. Use dashboard-get to look up tile IDs.'),
})

export type DeleteTileRequestApi = zod.input<typeof DeleteTileRequestApi>
export type DeleteTileRequestApiOutput = zod.output<typeof DeleteTileRequestApi>

export const MoveTileTileApi = zod.object({
    id: zod.number().describe('Dashboard tile ID to move.'),
})

export type MoveTileTileApi = zod.input<typeof MoveTileTileApi>
export type MoveTileTileApiOutput = zod.output<typeof MoveTileTileApi>

export const MoveTileRequestApi = zod.object({
    to_dashboard: zod.number().describe('Destination dashboard ID.'),
    tile: MoveTileTileApi.describe('Tile to move, identified by its dashboard tile ID.'),
})

export type MoveTileRequestApi = zod.input<typeof MoveTileRequestApi>
export type MoveTileRequestApiOutput = zod.output<typeof MoveTileRequestApi>

export const PatchedMoveTileRequestApi = zod.object({
    to_dashboard: zod.number().optional().describe('Destination dashboard ID.'),
    tile: MoveTileTileApi.optional().describe('Tile to move, identified by its dashboard tile ID.'),
})

export type PatchedMoveTileRequestApi = zod.input<typeof PatchedMoveTileRequestApi>
export type PatchedMoveTileRequestApiOutput = zod.output<typeof PatchedMoveTileRequestApi>

export const LayoutEnumApi = zod
    .enum(['preserve', 'two_column', 'full_width'])
    .describe('\* `preserve` - preserve\n\* `two_column` - two_column\n\* `full_width` - full_width')

export type LayoutEnumApi = zod.input<typeof LayoutEnumApi>
export type LayoutEnumApiOutput = zod.output<typeof LayoutEnumApi>

export const reorderTilesRequestApiLayoutDefault = `preserve`

export const ReorderTilesRequestApi = zod.object({
    tile_order: zod
        .array(zod.number())
        .min(1)
        .describe('Array of tile IDs in the desired display order (top to bottom, left to right).'),
    layout: LayoutEnumApi.default(reorderTilesRequestApiLayoutDefault).describe(
        "How to size tiles when reordering. 'preserve' (default) keeps each tile's existing width and height and only repacks positions in the new order. 'two_column' forces a 6-wide × 5-tall grid (two tiles per row). 'full_width' forces each tile to span the full 12-column row at height 5.\n\n\* `preserve` - preserve\n\* `two_column` - two_column\n\* `full_width` - full_width"
    ),
})

export type ReorderTilesRequestApi = zod.input<typeof ReorderTilesRequestApi>
export type ReorderTilesRequestApiOutput = zod.output<typeof ReorderTilesRequestApi>

export const InsightResultApi = zod
    .object({
        id: zod.number(),
        short_id: zod.string(),
        name: zod.string().nullable(),
        derived_name: zod.string().nullable(),
        result: zod.unknown(),
    })
    .describe('InsightSerializer restricted to identifiers + result only.')

export type InsightResultApi = zod.input<typeof InsightResultApi>
export type InsightResultApiOutput = zod.output<typeof InsightResultApi>

export const DashboardTileResultApi = zod
    .object({
        id: zod.number().optional(),
        insight: InsightResultApi,
    })
    .describe('DashboardTileSerializer restricted to tile id + insight result fields.')

export type DashboardTileResultApi = zod.input<typeof DashboardTileResultApi>
export type DashboardTileResultApiOutput = zod.output<typeof DashboardTileResultApi>

export const RunInsightsResponseApi = zod.object({
    results: zod.array(DashboardTileResultApi).describe('Results for each insight tile on the dashboard.'),
})

export type RunInsightsResponseApi = zod.input<typeof RunInsightsResponseApi>
export type RunInsightsResponseApiOutput = zod.output<typeof RunInsightsResponseApi>

export const DashboardWidgetRunResultApi = zod.object({
    tile_id: zod.number().describe('Dashboard tile ID for this widget result.'),
    widget_type: zod.string().nullable().describe('Widget type identifier, or null when the tile was not found.'),
    result: zod
        .unknown()
        .describe(
            'Live widget query result payload. List widgets return results (array), limit (configured page size), hasMore (boolean), totalCount (matching rows for current filters), totalCountCapped (true when totalCount hit the widget max and more may exist), and optional offset\/nextOffset. error_tracking_list results are issue summaries; session_replay_list results are recording metadata.'
        ),
    error: zod.string().nullable().describe('Error message when the widget could not be run.'),
})

export type DashboardWidgetRunResultApi = zod.input<typeof DashboardWidgetRunResultApi>
export type DashboardWidgetRunResultApiOutput = zod.output<typeof DashboardWidgetRunResultApi>

export const RunWidgetsResponseApi = zod.object({
    results: zod.array(DashboardWidgetRunResultApi).describe('Per-tile widget run results.'),
})

export type RunWidgetsResponseApi = zod.input<typeof RunWidgetsResponseApi>
export type RunWidgetsResponseApiOutput = zod.output<typeof RunWidgetsResponseApi>

export const DashboardSubscribeNudgeResponseApi = zod.object({
    created: zod
        .boolean()
        .describe(
            'Whether a nudge notification was created. False when one was already sent recently for this user and dashboard, or when in-app notifications are unavailable.'
        ),
})

export type DashboardSubscribeNudgeResponseApi = zod.input<typeof DashboardSubscribeNudgeResponseApi>
export type DashboardSubscribeNudgeResponseApiOutput = zod.output<typeof DashboardSubscribeNudgeResponseApi>

export const updateTextTileRequestApiBodyMax = 4000

export const updateTextTileRequestApiColorMax = 400

export const UpdateTextTileRequestApi = zod.object({
    tile_id: zod.number().describe('ID of the dashboard tile to update. Use dashboard-get to look up tile IDs.'),
    body: zod
        .string()
        .min(1)
        .max(updateTextTileRequestApiBodyMax)
        .optional()
        .describe('New markdown body for the text tile. Omit to leave the body unchanged. Max 4000 characters.'),
    layouts: TileLayoutsApi.optional().describe('New grid layout per breakpoint. Omit to leave the layout unchanged.'),
    color: zod
        .string()
        .max(updateTextTileRequestApiColorMax)
        .nullish()
        .describe('New accent color name, empty string or null to clear. Omit to leave unchanged.'),
})

export type UpdateTextTileRequestApi = zod.input<typeof UpdateTextTileRequestApi>
export type UpdateTextTileRequestApiOutput = zod.output<typeof UpdateTextTileRequestApi>

export const _WidgetTileLayoutBoxOpenApiApi = zod.object({
    x: zod.number().optional().describe('Column position in the dashboard grid (0-indexed).'),
    y: zod.number().optional().describe('Row position in the dashboard grid (0-indexed).'),
    w: zod.number().optional().describe('Width in grid columns. The desktop grid is 12 columns wide.'),
    h: zod.number().optional().describe('Height in grid rows.'),
})

export type _WidgetTileLayoutBoxOpenApiApi = zod.input<typeof _WidgetTileLayoutBoxOpenApiApi>
export type _WidgetTileLayoutBoxOpenApiApiOutput = zod.output<typeof _WidgetTileLayoutBoxOpenApiApi>

export const _WidgetTileLayoutsOpenApiApi = zod.object({
    sm: _WidgetTileLayoutBoxOpenApiApi
        .optional()
        .describe('Layout for the standard (desktop) breakpoint. The grid is 12 columns wide.'),
    xs: _WidgetTileLayoutBoxOpenApiApi
        .optional()
        .describe('Layout for the small (mobile) breakpoint. The grid is 1 column wide.'),
})

export type _WidgetTileLayoutsOpenApiApi = zod.input<typeof _WidgetTileLayoutsOpenApiApi>
export type _WidgetTileLayoutsOpenApiApiOutput = zod.output<typeof _WidgetTileLayoutsOpenApiApi>

export const activityEventsListWidgetAddRequestOpenApiApiNameMax = 400

export const ActivityEventsListWidgetAddRequestOpenApiApi = zod.object({
    name: zod
        .string()
        .max(activityEventsListWidgetAddRequestOpenApiApiNameMax)
        .nullish()
        .describe('Optional custom display name for the widget tile.'),
    description: zod
        .string()
        .optional()
        .describe('Optional markdown description shown when show_description is enabled.'),
    layouts: _WidgetTileLayoutsOpenApiApi
        .optional()
        .describe('Optional react-grid-layout positions keyed by breakpoint (sm, xs).'),
    show_description: zod.boolean().optional().describe('Whether to show the description on the dashboard tile.'),
    widget_type: zod.enum(['activity_events_list']),
    config: ActivityEventsListWidgetConfigApi.describe('Configuration for the recent events widget.'),
})

export type ActivityEventsListWidgetAddRequestOpenApiApi = zod.input<
    typeof ActivityEventsListWidgetAddRequestOpenApiApi
>
export type ActivityEventsListWidgetAddRequestOpenApiApiOutput = zod.output<
    typeof ActivityEventsListWidgetAddRequestOpenApiApi
>

export const errorTrackingListWidgetAddRequestOpenApiApiNameMax = 400

export const ErrorTrackingListWidgetAddRequestOpenApiApi = zod.object({
    name: zod
        .string()
        .max(errorTrackingListWidgetAddRequestOpenApiApiNameMax)
        .nullish()
        .describe('Optional custom display name for the widget tile.'),
    description: zod
        .string()
        .optional()
        .describe('Optional markdown description shown when show_description is enabled.'),
    layouts: _WidgetTileLayoutsOpenApiApi
        .optional()
        .describe('Optional react-grid-layout positions keyed by breakpoint (sm, xs).'),
    show_description: zod.boolean().optional().describe('Whether to show the description on the dashboard tile.'),
    widget_type: zod.enum(['error_tracking_list']),
    config: ErrorTrackingListWidgetConfigApi.describe('Configuration for the top issues widget.'),
})

export type ErrorTrackingListWidgetAddRequestOpenApiApi = zod.input<typeof ErrorTrackingListWidgetAddRequestOpenApiApi>
export type ErrorTrackingListWidgetAddRequestOpenApiApiOutput = zod.output<
    typeof ErrorTrackingListWidgetAddRequestOpenApiApi
>

export const sessionReplayListWidgetAddRequestOpenApiApiNameMax = 400

export const SessionReplayListWidgetAddRequestOpenApiApi = zod.object({
    name: zod
        .string()
        .max(sessionReplayListWidgetAddRequestOpenApiApiNameMax)
        .nullish()
        .describe('Optional custom display name for the widget tile.'),
    description: zod
        .string()
        .optional()
        .describe('Optional markdown description shown when show_description is enabled.'),
    layouts: _WidgetTileLayoutsOpenApiApi
        .optional()
        .describe('Optional react-grid-layout positions keyed by breakpoint (sm, xs).'),
    show_description: zod.boolean().optional().describe('Whether to show the description on the dashboard tile.'),
    widget_type: zod.enum(['session_replay_list']),
    config: SessionReplayListWidgetConfigApi.describe('Configuration for the recent recordings widget.'),
})

export type SessionReplayListWidgetAddRequestOpenApiApi = zod.input<typeof SessionReplayListWidgetAddRequestOpenApiApi>
export type SessionReplayListWidgetAddRequestOpenApiApiOutput = zod.output<
    typeof SessionReplayListWidgetAddRequestOpenApiApi
>

export const experimentsListWidgetAddRequestOpenApiApiNameMax = 400

export const ExperimentsListWidgetAddRequestOpenApiApi = zod.object({
    name: zod
        .string()
        .max(experimentsListWidgetAddRequestOpenApiApiNameMax)
        .nullish()
        .describe('Optional custom display name for the widget tile.'),
    description: zod
        .string()
        .optional()
        .describe('Optional markdown description shown when show_description is enabled.'),
    layouts: _WidgetTileLayoutsOpenApiApi
        .optional()
        .describe('Optional react-grid-layout positions keyed by breakpoint (sm, xs).'),
    show_description: zod.boolean().optional().describe('Whether to show the description on the dashboard tile.'),
    widget_type: zod.enum(['experiments_list']),
    config: ExperimentsListWidgetConfigApi.describe('Configuration for the experiments list widget.'),
})

export type ExperimentsListWidgetAddRequestOpenApiApi = zod.input<typeof ExperimentsListWidgetAddRequestOpenApiApi>
export type ExperimentsListWidgetAddRequestOpenApiApiOutput = zod.output<
    typeof ExperimentsListWidgetAddRequestOpenApiApi
>

export const experimentResultsWidgetAddRequestOpenApiApiNameMax = 400

export const ExperimentResultsWidgetAddRequestOpenApiApi = zod.object({
    name: zod
        .string()
        .max(experimentResultsWidgetAddRequestOpenApiApiNameMax)
        .nullish()
        .describe('Optional custom display name for the widget tile.'),
    description: zod
        .string()
        .optional()
        .describe('Optional markdown description shown when show_description is enabled.'),
    layouts: _WidgetTileLayoutsOpenApiApi
        .optional()
        .describe('Optional react-grid-layout positions keyed by breakpoint (sm, xs).'),
    show_description: zod.boolean().optional().describe('Whether to show the description on the dashboard tile.'),
    widget_type: zod.enum(['experiment_results']),
    config: ExperimentResultsWidgetConfigApi.describe('Configuration for the experiment results widget.'),
})

export type ExperimentResultsWidgetAddRequestOpenApiApi = zod.input<typeof ExperimentResultsWidgetAddRequestOpenApiApi>
export type ExperimentResultsWidgetAddRequestOpenApiApiOutput = zod.output<
    typeof ExperimentResultsWidgetAddRequestOpenApiApi
>

export const surveyResultsWidgetAddRequestOpenApiApiNameMax = 400

export const SurveyResultsWidgetAddRequestOpenApiApi = zod.object({
    name: zod
        .string()
        .max(surveyResultsWidgetAddRequestOpenApiApiNameMax)
        .nullish()
        .describe('Optional custom display name for the widget tile.'),
    description: zod
        .string()
        .optional()
        .describe('Optional markdown description shown when show_description is enabled.'),
    layouts: _WidgetTileLayoutsOpenApiApi
        .optional()
        .describe('Optional react-grid-layout positions keyed by breakpoint (sm, xs).'),
    show_description: zod.boolean().optional().describe('Whether to show the description on the dashboard tile.'),
    widget_type: zod.enum(['survey_results']),
    config: SurveyResultsWidgetConfigApi.describe('Configuration for the survey results widget.'),
})

export type SurveyResultsWidgetAddRequestOpenApiApi = zod.input<typeof SurveyResultsWidgetAddRequestOpenApiApi>
export type SurveyResultsWidgetAddRequestOpenApiApiOutput = zod.output<typeof SurveyResultsWidgetAddRequestOpenApiApi>

export const logsListWidgetAddRequestOpenApiApiNameMax = 400

export const LogsListWidgetAddRequestOpenApiApi = zod.object({
    name: zod
        .string()
        .max(logsListWidgetAddRequestOpenApiApiNameMax)
        .nullish()
        .describe('Optional custom display name for the widget tile.'),
    description: zod
        .string()
        .optional()
        .describe('Optional markdown description shown when show_description is enabled.'),
    layouts: _WidgetTileLayoutsOpenApiApi
        .optional()
        .describe('Optional react-grid-layout positions keyed by breakpoint (sm, xs).'),
    show_description: zod.boolean().optional().describe('Whether to show the description on the dashboard tile.'),
    widget_type: zod.enum(['logs_list']),
    config: LogsListWidgetConfigApi.describe('Configuration for the recent logs widget.'),
})

export type LogsListWidgetAddRequestOpenApiApi = zod.input<typeof LogsListWidgetAddRequestOpenApiApi>
export type LogsListWidgetAddRequestOpenApiApiOutput = zod.output<typeof LogsListWidgetAddRequestOpenApiApi>

export const AddDashboardWidgetRequestApi = zod.union([
    ActivityEventsListWidgetAddRequestOpenApiApi,
    ErrorTrackingListWidgetAddRequestOpenApiApi,
    SessionReplayListWidgetAddRequestOpenApiApi,
    ExperimentsListWidgetAddRequestOpenApiApi,
    ExperimentResultsWidgetAddRequestOpenApiApi,
    SurveyResultsWidgetAddRequestOpenApiApi,
    LogsListWidgetAddRequestOpenApiApi,
])

export type AddDashboardWidgetRequestApi = zod.input<typeof AddDashboardWidgetRequestApi>
export type AddDashboardWidgetRequestApiOutput = zod.output<typeof AddDashboardWidgetRequestApi>

export const addDashboardWidgetsBatchRequestOpenApiApiWidgetsMax = 10

export const AddDashboardWidgetsBatchRequestOpenApiApi = zod
    .object({
        widgets: zod
            .array(AddDashboardWidgetRequestApi)
            .min(1)
            .max(addDashboardWidgetsBatchRequestOpenApiApiWidgetsMax)
            .describe(
                'Widget tiles to add atomically. Supported widget_type values: activity_events_list, error_tracking_list, experiment_results, experiments_list, logs_list, session_replay_list, survey_results. Use dashboard-widget-catalog-list for per-type config_schema documentation. (1–10 per request).'
            ),
    })
    .describe('OpenAPI-only batch-add schema with widget_type-discriminated config shapes for agents.')

export type AddDashboardWidgetsBatchRequestOpenApiApi = zod.input<typeof AddDashboardWidgetsBatchRequestOpenApiApi>
export type AddDashboardWidgetsBatchRequestOpenApiApiOutput = zod.output<
    typeof AddDashboardWidgetsBatchRequestOpenApiApi
>

export const AddDashboardWidgetsBatchResponseApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type AddDashboardWidgetsBatchResponseApi = zod.input<typeof AddDashboardWidgetsBatchResponseApi>
export type AddDashboardWidgetsBatchResponseApiOutput = zod.output<typeof AddDashboardWidgetsBatchResponseApi>

export const activityEventsListWidgetUpdateRequestOpenApiApiNameMax = 400

export const ActivityEventsListWidgetUpdateRequestOpenApiApi = zod.object({
    tile_id: zod.number().describe('ID of the widget tile to update. Use dashboard-get to look up widget tile IDs.'),
    name: zod
        .string()
        .max(activityEventsListWidgetUpdateRequestOpenApiApiNameMax)
        .nullish()
        .describe('New display name for the widget. Empty string or null clears it; omit to leave unchanged.'),
    description: zod.string().optional().describe('New markdown description for the widget. Omit to leave unchanged.'),
    widget_type: zod.enum(['activity_events_list']),
    config: ActivityEventsListWidgetConfigApi.optional().describe(
        'New configuration for the recent events widget. Omit to leave unchanged.'
    ),
})

export type ActivityEventsListWidgetUpdateRequestOpenApiApi = zod.input<
    typeof ActivityEventsListWidgetUpdateRequestOpenApiApi
>
export type ActivityEventsListWidgetUpdateRequestOpenApiApiOutput = zod.output<
    typeof ActivityEventsListWidgetUpdateRequestOpenApiApi
>

export const errorTrackingListWidgetUpdateRequestOpenApiApiNameMax = 400

export const ErrorTrackingListWidgetUpdateRequestOpenApiApi = zod.object({
    tile_id: zod.number().describe('ID of the widget tile to update. Use dashboard-get to look up widget tile IDs.'),
    name: zod
        .string()
        .max(errorTrackingListWidgetUpdateRequestOpenApiApiNameMax)
        .nullish()
        .describe('New display name for the widget. Empty string or null clears it; omit to leave unchanged.'),
    description: zod.string().optional().describe('New markdown description for the widget. Omit to leave unchanged.'),
    widget_type: zod.enum(['error_tracking_list']),
    config: ErrorTrackingListWidgetConfigApi.optional().describe(
        'New configuration for the top issues widget. Omit to leave unchanged.'
    ),
})

export type ErrorTrackingListWidgetUpdateRequestOpenApiApi = zod.input<
    typeof ErrorTrackingListWidgetUpdateRequestOpenApiApi
>
export type ErrorTrackingListWidgetUpdateRequestOpenApiApiOutput = zod.output<
    typeof ErrorTrackingListWidgetUpdateRequestOpenApiApi
>

export const sessionReplayListWidgetUpdateRequestOpenApiApiNameMax = 400

export const SessionReplayListWidgetUpdateRequestOpenApiApi = zod.object({
    tile_id: zod.number().describe('ID of the widget tile to update. Use dashboard-get to look up widget tile IDs.'),
    name: zod
        .string()
        .max(sessionReplayListWidgetUpdateRequestOpenApiApiNameMax)
        .nullish()
        .describe('New display name for the widget. Empty string or null clears it; omit to leave unchanged.'),
    description: zod.string().optional().describe('New markdown description for the widget. Omit to leave unchanged.'),
    widget_type: zod.enum(['session_replay_list']),
    config: SessionReplayListWidgetConfigApi.optional().describe(
        'New configuration for the recent recordings widget. Omit to leave unchanged.'
    ),
})

export type SessionReplayListWidgetUpdateRequestOpenApiApi = zod.input<
    typeof SessionReplayListWidgetUpdateRequestOpenApiApi
>
export type SessionReplayListWidgetUpdateRequestOpenApiApiOutput = zod.output<
    typeof SessionReplayListWidgetUpdateRequestOpenApiApi
>

export const experimentsListWidgetUpdateRequestOpenApiApiNameMax = 400

export const ExperimentsListWidgetUpdateRequestOpenApiApi = zod.object({
    tile_id: zod.number().describe('ID of the widget tile to update. Use dashboard-get to look up widget tile IDs.'),
    name: zod
        .string()
        .max(experimentsListWidgetUpdateRequestOpenApiApiNameMax)
        .nullish()
        .describe('New display name for the widget. Empty string or null clears it; omit to leave unchanged.'),
    description: zod.string().optional().describe('New markdown description for the widget. Omit to leave unchanged.'),
    widget_type: zod.enum(['experiments_list']),
    config: ExperimentsListWidgetConfigApi.optional().describe(
        'New configuration for the experiments list widget. Omit to leave unchanged.'
    ),
})

export type ExperimentsListWidgetUpdateRequestOpenApiApi = zod.input<
    typeof ExperimentsListWidgetUpdateRequestOpenApiApi
>
export type ExperimentsListWidgetUpdateRequestOpenApiApiOutput = zod.output<
    typeof ExperimentsListWidgetUpdateRequestOpenApiApi
>

export const experimentResultsWidgetUpdateRequestOpenApiApiNameMax = 400

export const ExperimentResultsWidgetUpdateRequestOpenApiApi = zod.object({
    tile_id: zod.number().describe('ID of the widget tile to update. Use dashboard-get to look up widget tile IDs.'),
    name: zod
        .string()
        .max(experimentResultsWidgetUpdateRequestOpenApiApiNameMax)
        .nullish()
        .describe('New display name for the widget. Empty string or null clears it; omit to leave unchanged.'),
    description: zod.string().optional().describe('New markdown description for the widget. Omit to leave unchanged.'),
    widget_type: zod.enum(['experiment_results']),
    config: ExperimentResultsWidgetConfigApi.optional().describe(
        'New configuration for the experiment results widget. Omit to leave unchanged.'
    ),
})

export type ExperimentResultsWidgetUpdateRequestOpenApiApi = zod.input<
    typeof ExperimentResultsWidgetUpdateRequestOpenApiApi
>
export type ExperimentResultsWidgetUpdateRequestOpenApiApiOutput = zod.output<
    typeof ExperimentResultsWidgetUpdateRequestOpenApiApi
>

export const surveyResultsWidgetUpdateRequestOpenApiApiNameMax = 400

export const SurveyResultsWidgetUpdateRequestOpenApiApi = zod.object({
    tile_id: zod.number().describe('ID of the widget tile to update. Use dashboard-get to look up widget tile IDs.'),
    name: zod
        .string()
        .max(surveyResultsWidgetUpdateRequestOpenApiApiNameMax)
        .nullish()
        .describe('New display name for the widget. Empty string or null clears it; omit to leave unchanged.'),
    description: zod.string().optional().describe('New markdown description for the widget. Omit to leave unchanged.'),
    widget_type: zod.enum(['survey_results']),
    config: SurveyResultsWidgetConfigApi.optional().describe(
        'New configuration for the survey results widget. Omit to leave unchanged.'
    ),
})

export type SurveyResultsWidgetUpdateRequestOpenApiApi = zod.input<typeof SurveyResultsWidgetUpdateRequestOpenApiApi>
export type SurveyResultsWidgetUpdateRequestOpenApiApiOutput = zod.output<
    typeof SurveyResultsWidgetUpdateRequestOpenApiApi
>

export const logsListWidgetUpdateRequestOpenApiApiNameMax = 400

export const LogsListWidgetUpdateRequestOpenApiApi = zod.object({
    tile_id: zod.number().describe('ID of the widget tile to update. Use dashboard-get to look up widget tile IDs.'),
    name: zod
        .string()
        .max(logsListWidgetUpdateRequestOpenApiApiNameMax)
        .nullish()
        .describe('New display name for the widget. Empty string or null clears it; omit to leave unchanged.'),
    description: zod.string().optional().describe('New markdown description for the widget. Omit to leave unchanged.'),
    widget_type: zod.enum(['logs_list']),
    config: LogsListWidgetConfigApi.optional().describe(
        'New configuration for the recent logs widget. Omit to leave unchanged.'
    ),
})

export type LogsListWidgetUpdateRequestOpenApiApi = zod.input<typeof LogsListWidgetUpdateRequestOpenApiApi>
export type LogsListWidgetUpdateRequestOpenApiApiOutput = zod.output<typeof LogsListWidgetUpdateRequestOpenApiApi>

export const UpdateDashboardWidgetRequestApi = zod.union([
    ActivityEventsListWidgetUpdateRequestOpenApiApi,
    ErrorTrackingListWidgetUpdateRequestOpenApiApi,
    SessionReplayListWidgetUpdateRequestOpenApiApi,
    ExperimentsListWidgetUpdateRequestOpenApiApi,
    ExperimentResultsWidgetUpdateRequestOpenApiApi,
    SurveyResultsWidgetUpdateRequestOpenApiApi,
    LogsListWidgetUpdateRequestOpenApiApi,
])

export type UpdateDashboardWidgetRequestApi = zod.input<typeof UpdateDashboardWidgetRequestApi>
export type UpdateDashboardWidgetRequestApiOutput = zod.output<typeof UpdateDashboardWidgetRequestApi>

export const patchedUpdateDashboardWidgetsBatchRequestOpenApiApiWidgetsMax = 10

export const PatchedUpdateDashboardWidgetsBatchRequestOpenApiApi = zod
    .object({
        widgets: zod
            .array(UpdateDashboardWidgetRequestApi)
            .min(1)
            .max(patchedUpdateDashboardWidgetsBatchRequestOpenApiApiWidgetsMax)
            .optional()
            .describe(
                'Widget tiles to update atomically, each identified by its tile_id. config shape is per widget_type; see dashboard-widget-catalog-list for per-type config_schema (1–10 per request).'
            ),
    })
    .describe('OpenAPI-only batch-update schema with widget_type-discriminated config shapes for agents.')

export type PatchedUpdateDashboardWidgetsBatchRequestOpenApiApi = zod.input<
    typeof PatchedUpdateDashboardWidgetsBatchRequestOpenApiApi
>
export type PatchedUpdateDashboardWidgetsBatchRequestOpenApiApiOutput = zod.output<
    typeof PatchedUpdateDashboardWidgetsBatchRequestOpenApiApi
>

export const UpdateDashboardWidgetsBatchResponseApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type UpdateDashboardWidgetsBatchResponseApi = zod.input<typeof UpdateDashboardWidgetsBatchResponseApi>
export type UpdateDashboardWidgetsBatchResponseApiOutput = zod.output<typeof UpdateDashboardWidgetsBatchResponseApi>

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

export const ActivityEventsListWidgetCatalogEntryOpenApiApi = zod.object({
    widget_type: zod.enum(['activity_events_list']),
    group_id: zod.string(),
    group_label: zod.string(),
    label: zod.string(),
    description: zod.string(),
    config_schema: ActivityEventsListWidgetConfigApi.describe(
        'OpenAPI config shape for this widget type (documentation; matches batch-add\/PATCH schemas).'
    ),
    required_product_access: zod.string().nullish(),
})

export type ActivityEventsListWidgetCatalogEntryOpenApiApi = zod.input<
    typeof ActivityEventsListWidgetCatalogEntryOpenApiApi
>
export type ActivityEventsListWidgetCatalogEntryOpenApiApiOutput = zod.output<
    typeof ActivityEventsListWidgetCatalogEntryOpenApiApi
>

export const ErrorTrackingListWidgetCatalogEntryOpenApiApi = zod.object({
    widget_type: zod.enum(['error_tracking_list']),
    group_id: zod.string(),
    group_label: zod.string(),
    label: zod.string(),
    description: zod.string(),
    config_schema: ErrorTrackingListWidgetConfigApi.describe(
        'OpenAPI config shape for this widget type (documentation; matches batch-add\/PATCH schemas).'
    ),
    required_product_access: zod.string().nullish(),
})

export type ErrorTrackingListWidgetCatalogEntryOpenApiApi = zod.input<
    typeof ErrorTrackingListWidgetCatalogEntryOpenApiApi
>
export type ErrorTrackingListWidgetCatalogEntryOpenApiApiOutput = zod.output<
    typeof ErrorTrackingListWidgetCatalogEntryOpenApiApi
>

export const SessionReplayListWidgetCatalogEntryOpenApiApi = zod.object({
    widget_type: zod.enum(['session_replay_list']),
    group_id: zod.string(),
    group_label: zod.string(),
    label: zod.string(),
    description: zod.string(),
    config_schema: SessionReplayListWidgetConfigApi.describe(
        'OpenAPI config shape for this widget type (documentation; matches batch-add\/PATCH schemas).'
    ),
    required_product_access: zod.string().nullish(),
})

export type SessionReplayListWidgetCatalogEntryOpenApiApi = zod.input<
    typeof SessionReplayListWidgetCatalogEntryOpenApiApi
>
export type SessionReplayListWidgetCatalogEntryOpenApiApiOutput = zod.output<
    typeof SessionReplayListWidgetCatalogEntryOpenApiApi
>

export const ExperimentsListWidgetCatalogEntryOpenApiApi = zod.object({
    widget_type: zod.enum(['experiments_list']),
    group_id: zod.string(),
    group_label: zod.string(),
    label: zod.string(),
    description: zod.string(),
    config_schema: ExperimentsListWidgetConfigApi.describe(
        'OpenAPI config shape for this widget type (documentation; matches batch-add\/PATCH schemas).'
    ),
    required_product_access: zod.string().nullish(),
})

export type ExperimentsListWidgetCatalogEntryOpenApiApi = zod.input<typeof ExperimentsListWidgetCatalogEntryOpenApiApi>
export type ExperimentsListWidgetCatalogEntryOpenApiApiOutput = zod.output<
    typeof ExperimentsListWidgetCatalogEntryOpenApiApi
>

export const ExperimentResultsWidgetCatalogEntryOpenApiApi = zod.object({
    widget_type: zod.enum(['experiment_results']),
    group_id: zod.string(),
    group_label: zod.string(),
    label: zod.string(),
    description: zod.string(),
    config_schema: ExperimentResultsWidgetConfigApi.describe(
        'OpenAPI config shape for this widget type (documentation; matches batch-add\/PATCH schemas).'
    ),
    required_product_access: zod.string().nullish(),
})

export type ExperimentResultsWidgetCatalogEntryOpenApiApi = zod.input<
    typeof ExperimentResultsWidgetCatalogEntryOpenApiApi
>
export type ExperimentResultsWidgetCatalogEntryOpenApiApiOutput = zod.output<
    typeof ExperimentResultsWidgetCatalogEntryOpenApiApi
>

export const SurveyResultsWidgetCatalogEntryOpenApiApi = zod.object({
    widget_type: zod.enum(['survey_results']),
    group_id: zod.string(),
    group_label: zod.string(),
    label: zod.string(),
    description: zod.string(),
    config_schema: SurveyResultsWidgetConfigApi.describe(
        'OpenAPI config shape for this widget type (documentation; matches batch-add\/PATCH schemas).'
    ),
    required_product_access: zod.string().nullish(),
})

export type SurveyResultsWidgetCatalogEntryOpenApiApi = zod.input<typeof SurveyResultsWidgetCatalogEntryOpenApiApi>
export type SurveyResultsWidgetCatalogEntryOpenApiApiOutput = zod.output<
    typeof SurveyResultsWidgetCatalogEntryOpenApiApi
>

export const LogsListWidgetCatalogEntryOpenApiApi = zod.object({
    widget_type: zod.enum(['logs_list']),
    group_id: zod.string(),
    group_label: zod.string(),
    label: zod.string(),
    description: zod.string(),
    config_schema: LogsListWidgetConfigApi.describe(
        'OpenAPI config shape for this widget type (documentation; matches batch-add\/PATCH schemas).'
    ),
    required_product_access: zod.string().nullish(),
})

export type LogsListWidgetCatalogEntryOpenApiApi = zod.input<typeof LogsListWidgetCatalogEntryOpenApiApi>
export type LogsListWidgetCatalogEntryOpenApiApiOutput = zod.output<typeof LogsListWidgetCatalogEntryOpenApiApi>

export const WidgetCatalogEntryApi = zod.union([
    ActivityEventsListWidgetCatalogEntryOpenApiApi,
    ErrorTrackingListWidgetCatalogEntryOpenApiApi,
    SessionReplayListWidgetCatalogEntryOpenApiApi,
    ExperimentsListWidgetCatalogEntryOpenApiApi,
    ExperimentResultsWidgetCatalogEntryOpenApiApi,
    SurveyResultsWidgetCatalogEntryOpenApiApi,
    LogsListWidgetCatalogEntryOpenApiApi,
])

export type WidgetCatalogEntryApi = zod.input<typeof WidgetCatalogEntryApi>
export type WidgetCatalogEntryApiOutput = zod.output<typeof WidgetCatalogEntryApi>

export const WidgetCatalogResponseApi = zod.object({
    results: zod
        .array(WidgetCatalogEntryApi)
        .describe('Registered dashboard widget types available when dashboard-widgets is enabled.'),
})

export type WidgetCatalogResponseApi = zod.input<typeof WidgetCatalogResponseApi>
export type WidgetCatalogResponseApiOutput = zod.output<typeof WidgetCatalogResponseApi>

export const dataColorThemeApiNameMax = 100

export const DataColorThemeApi = zod.object({
    id: zod.number(),
    name: zod.string().max(dataColorThemeApiNameMax),
    colors: zod.unknown().optional(),
    is_global: zod.boolean(),
    created_at: zod.iso.datetime({ offset: true }).nullable(),
    created_by: UserBasicApi,
})

export type DataColorThemeApi = zod.input<typeof DataColorThemeApi>
export type DataColorThemeApiOutput = zod.output<typeof DataColorThemeApi>

export const PaginatedDataColorThemeListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(DataColorThemeApi),
})

export type PaginatedDataColorThemeListApi = zod.input<typeof PaginatedDataColorThemeListApi>
export type PaginatedDataColorThemeListApiOutput = zod.output<typeof PaginatedDataColorThemeListApi>

export const patchedDataColorThemeApiNameMax = 100

export const PatchedDataColorThemeApi = zod.object({
    id: zod.number().optional(),
    name: zod.string().max(patchedDataColorThemeApiNameMax).optional(),
    colors: zod.unknown().optional(),
    is_global: zod.boolean().optional(),
    created_at: zod.iso.datetime({ offset: true }).nullish(),
    created_by: UserBasicApi.optional(),
})

export type PatchedDataColorThemeApi = zod.input<typeof PatchedDataColorThemeApi>
export type PatchedDataColorThemeApiOutput = zod.output<typeof PatchedDataColorThemeApi>

export const InsightApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type InsightApi = zod.input<typeof InsightApi>
export type InsightApiOutput = zod.output<typeof InsightApi>

export const DashboardTileBasicApi = zod.object({
    id: zod.number(),
    dashboard_id: zod.number(),
    deleted: zod.boolean().nullish(),
})

export type DashboardTileBasicApi = zod.input<typeof DashboardTileBasicApi>
export type DashboardTileBasicApiOutput = zod.output<typeof DashboardTileBasicApi>

export const textApiBodyMax = 4000

export const TextApi = zod.object({
    id: zod.number(),
    created_by: UserBasicApi,
    last_modified_by: UserBasicApi,
    body: zod.string().max(textApiBodyMax).nullish(),
    dashboard_tiles: zod.array(DashboardTileBasicApi),
    last_modified_at: zod.iso.datetime({ offset: true }),
    team: zod.number(),
})

export type TextApi = zod.input<typeof TextApi>
export type TextApiOutput = zod.output<typeof TextApi>

export const PlacementEnumApi = zod.enum(['left', 'right']).describe('\* `left` - left\n\* `right` - right')

export type PlacementEnumApi = zod.input<typeof PlacementEnumApi>
export type PlacementEnumApiOutput = zod.output<typeof PlacementEnumApi>

export const StyleEnumApi = zod
    .enum(['primary', 'secondary'])
    .describe('\* `primary` - Primary\n\* `secondary` - Secondary')

export type StyleEnumApi = zod.input<typeof StyleEnumApi>
export type StyleEnumApiOutput = zod.output<typeof StyleEnumApi>

export const buttonTileApiUrlMax = 2000

export const buttonTileApiTextMax = 200

export const buttonTileApiPlacementDefault = `left`

export const ButtonTileApi = zod.object({
    id: zod.uuid(),
    created_by: UserBasicApi,
    last_modified_by: UserBasicApi,
    url: zod.string().max(buttonTileApiUrlMax),
    text: zod.string().max(buttonTileApiTextMax),
    placement: PlacementEnumApi.default(buttonTileApiPlacementDefault),
    dashboard_tiles: zod.array(DashboardTileBasicApi),
    style: StyleEnumApi.optional(),
    last_modified_at: zod.iso.datetime({ offset: true }),
    team: zod.number(),
})

export type ButtonTileApi = zod.input<typeof ButtonTileApi>
export type ButtonTileApiOutput = zod.output<typeof ButtonTileApi>

export const dashboardWidgetApiWidgetTypeMax = 64

export const dashboardWidgetApiNameMax = 400

export const DashboardWidgetApi = zod.object({
    id: zod.uuid(),
    created_by: UserBasicApi,
    last_modified_by: UserBasicApi,
    widget_type: zod
        .string()
        .max(dashboardWidgetApiWidgetTypeMax)
        .describe('Widget type identifier from the dashboard widget catalog.'),
    name: zod
        .string()
        .max(dashboardWidgetApiNameMax)
        .nullish()
        .describe(
            'Optional custom display name for this widget tile. Falls back to the widget catalog label when unset.'
        ),
    description: zod
        .string()
        .optional()
        .describe('Optional markdown description shown on the dashboard tile when enabled.'),
    config: DashboardWidgetConfigApi.optional().describe('Widget-specific configuration JSON for this widget type.'),
    dashboard_tiles: zod.array(DashboardTileBasicApi),
    last_modified_at: zod.iso.datetime({ offset: true }),
    team: zod.number(),
})

export type DashboardWidgetApi = zod.input<typeof DashboardWidgetApi>
export type DashboardWidgetApiOutput = zod.output<typeof DashboardWidgetApi>

export const _InsightQuerySchemaApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type _InsightQuerySchemaApi = zod.input<typeof _InsightQuerySchemaApi>
export type _InsightQuerySchemaApiOutput = zod.output<typeof _InsightQuerySchemaApi>

export const InsightFilterOverrideContextApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type InsightFilterOverrideContextApi = zod.input<typeof InsightFilterOverrideContextApi>
export type InsightFilterOverrideContextApiOutput = zod.output<typeof InsightFilterOverrideContextApi>

export const InsightVizNodeApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type InsightVizNodeApi = zod.input<typeof InsightVizNodeApi>
export type InsightVizNodeApiOutput = zod.output<typeof InsightVizNodeApi>

export const DataTableNodeApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type DataTableNodeApi = zod.input<typeof DataTableNodeApi>
export type DataTableNodeApiOutput = zod.output<typeof DataTableNodeApi>

export const DataVisualizationNodeApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type DataVisualizationNodeApi = zod.input<typeof DataVisualizationNodeApi>
export type DataVisualizationNodeApiOutput = zod.output<typeof DataVisualizationNodeApi>

export const BounceRatePageViewModeApi = zod.enum(['count_pageviews', 'uniq_urls', 'uniq_page_screen_autocaptures'])

export type BounceRatePageViewModeApi = zod.input<typeof BounceRatePageViewModeApi>
export type BounceRatePageViewModeApiOutput = zod.output<typeof BounceRatePageViewModeApi>

export const FilterLogicalOperatorApi = zod.enum(['AND', 'OR'])

export type FilterLogicalOperatorApi = zod.input<typeof FilterLogicalOperatorApi>
export type FilterLogicalOperatorApiOutput = zod.output<typeof FilterLogicalOperatorApi>

export const CustomChannelFieldApi = zod.enum([
    'utm_source',
    'utm_medium',
    'utm_campaign',
    'referring_domain',
    'url',
    'pathname',
    'hostname',
])

export type CustomChannelFieldApi = zod.input<typeof CustomChannelFieldApi>
export type CustomChannelFieldApiOutput = zod.output<typeof CustomChannelFieldApi>

export const CustomChannelOperatorApi = zod.enum([
    'exact',
    'is_not',
    'is_set',
    'is_not_set',
    'icontains',
    'not_icontains',
    'regex',
    'not_regex',
])

export type CustomChannelOperatorApi = zod.input<typeof CustomChannelOperatorApi>
export type CustomChannelOperatorApiOutput = zod.output<typeof CustomChannelOperatorApi>

export const CustomChannelConditionApi = zod.object({
    id: zod.string(),
    key: CustomChannelFieldApi,
    op: CustomChannelOperatorApi,
    value: zod.union([zod.string(), zod.array(zod.string()), zod.null()]).optional(),
})

export type CustomChannelConditionApi = zod.input<typeof CustomChannelConditionApi>
export type CustomChannelConditionApiOutput = zod.output<typeof CustomChannelConditionApi>

export const CustomChannelRuleApi = zod.object({
    channel_type: zod.string(),
    combiner: FilterLogicalOperatorApi,
    id: zod.string(),
    items: zod.array(CustomChannelConditionApi),
})

export type CustomChannelRuleApi = zod.input<typeof CustomChannelRuleApi>
export type CustomChannelRuleApiOutput = zod.output<typeof CustomChannelRuleApi>

export const DataWarehouseEventsModifierApi = zod.object({
    distinct_id_field: zod.string(),
    id_field: zod.string(),
    table_name: zod.string(),
    timestamp_field: zod.string(),
})

export type DataWarehouseEventsModifierApi = zod.input<typeof DataWarehouseEventsModifierApi>
export type DataWarehouseEventsModifierApiOutput = zod.output<typeof DataWarehouseEventsModifierApi>

export const InCohortViaApi = zod.enum(['auto', 'leftjoin', 'subquery', 'leftjoin_conjoined'])

export type InCohortViaApi = zod.input<typeof InCohortViaApi>
export type InCohortViaApiOutput = zod.output<typeof InCohortViaApi>

export const InlineCohortCalculationApi = zod.enum(['off', 'auto', 'always'])

export type InlineCohortCalculationApi = zod.input<typeof InlineCohortCalculationApi>
export type InlineCohortCalculationApiOutput = zod.output<typeof InlineCohortCalculationApi>

export const MaterializationModeApi = zod.enum(['auto', 'legacy_null_as_string', 'legacy_null_as_null', 'disabled'])

export type MaterializationModeApi = zod.input<typeof MaterializationModeApi>
export type MaterializationModeApiOutput = zod.output<typeof MaterializationModeApi>

export const MaterializedColumnsOptimizationModeApi = zod.enum(['disabled', 'optimized'])

export type MaterializedColumnsOptimizationModeApi = zod.input<typeof MaterializedColumnsOptimizationModeApi>
export type MaterializedColumnsOptimizationModeApiOutput = zod.output<typeof MaterializedColumnsOptimizationModeApi>

export const ParserModeApi = zod.enum([
    'cpp_only',
    'cpp_with_rust_shadow',
    'cpp_with_rust_py_shadow',
    'rust_with_cpp_shadow',
    'rust_only',
    'rust_py_only',
    'rust_py_with_cpp_shadow',
])

export type ParserModeApi = zod.input<typeof ParserModeApi>
export type ParserModeApiOutput = zod.output<typeof ParserModeApi>

export const PersonsArgMaxVersionApi = zod.enum(['auto', 'v1', 'v2'])

export type PersonsArgMaxVersionApi = zod.input<typeof PersonsArgMaxVersionApi>
export type PersonsArgMaxVersionApiOutput = zod.output<typeof PersonsArgMaxVersionApi>

export const PersonsJoinModeApi = zod.enum(['inner', 'left'])

export type PersonsJoinModeApi = zod.input<typeof PersonsJoinModeApi>
export type PersonsJoinModeApiOutput = zod.output<typeof PersonsJoinModeApi>

export const PersonsOnEventsModeApi = zod.enum([
    'disabled',
    'person_id_no_override_properties_on_events',
    'person_id_override_properties_on_events',
    'person_id_override_properties_joined',
])

export type PersonsOnEventsModeApi = zod.input<typeof PersonsOnEventsModeApi>
export type PersonsOnEventsModeApiOutput = zod.output<typeof PersonsOnEventsModeApi>

export const PropertyGroupsModeApi = zod.enum(['enabled', 'disabled', 'optimized'])

export type PropertyGroupsModeApi = zod.input<typeof PropertyGroupsModeApi>
export type PropertyGroupsModeApiOutput = zod.output<typeof PropertyGroupsModeApi>

export const SessionTableVersionApi = zod.enum(['auto', 'v1', 'v2', 'v3'])

export type SessionTableVersionApi = zod.input<typeof SessionTableVersionApi>
export type SessionTableVersionApiOutput = zod.output<typeof SessionTableVersionApi>

export const SessionsV2JoinModeApi = zod.enum(['string', 'uuid'])

export type SessionsV2JoinModeApi = zod.input<typeof SessionsV2JoinModeApi>
export type SessionsV2JoinModeApiOutput = zod.output<typeof SessionsV2JoinModeApi>

export const HogQLQueryModifiersApi = zod.object({
    bounceRateDurationSeconds: zod.union([zod.number(), zod.null()]).optional(),
    bounceRatePageViewMode: zod.union([BounceRatePageViewModeApi, zod.null()]).optional(),
    convertToProjectTimezone: zod.union([zod.boolean(), zod.null()]).optional(),
    customChannelTypeRules: zod.union([zod.array(CustomChannelRuleApi), zod.null()]).optional(),
    dataWarehouseEventsModifiers: zod.union([zod.array(DataWarehouseEventsModifierApi), zod.null()]).optional(),
    debug: zod.union([zod.boolean(), zod.null()]).optional(),
    forceClickhouseDataSkippingIndexes: zod
        .union([zod.array(zod.string()), zod.null()])
        .optional()
        .describe('If these are provided, the query will fail if these skip indexes are not used'),
    formatCsvAllowDoubleQuotes: zod.union([zod.boolean(), zod.null()]).optional(),
    inCohortVia: zod.union([InCohortViaApi, zod.null()]).optional(),
    inlineCohortCalculation: zod.union([InlineCohortCalculationApi, zod.null()]).optional(),
    materializationMode: zod.union([MaterializationModeApi, zod.null()]).optional(),
    materializedColumnsOptimizationMode: zod.union([MaterializedColumnsOptimizationModeApi, zod.null()]).optional(),
    optimizeJoinedFilters: zod.union([zod.boolean(), zod.null()]).optional(),
    optimizeProjections: zod.union([zod.boolean(), zod.null()]).optional(),
    parserMode: zod
        .union([ParserModeApi, zod.null()])
        .optional()
        .describe(
            'HogQL parser backend; absent → `rust_py_with_cpp_shadow` (rust-py is primary, cpp runs as a sampled shadow). `\*_shadow` modes return the primary result and sample-compare against the other parser, reporting divergences without failing the request. The `rust_py_\*` modes drive the same hand-rolled Rust parser as `rust_\*` but build `posthog.hogql.ast` dataclass instances directly via PyO3, skipping the JSON round-trip.'
        ),
    personsArgMaxVersion: zod.union([PersonsArgMaxVersionApi, zod.null()]).optional(),
    personsJoinMode: zod.union([PersonsJoinModeApi, zod.null()]).optional(),
    personsOnEventsMode: zod.union([PersonsOnEventsModeApi, zod.null()]).optional(),
    propertyGroupsMode: zod.union([PropertyGroupsModeApi, zod.null()]).optional(),
    pushDownPredicates: zod.union([zod.boolean(), zod.null()]).optional(),
    s3TableUseInvalidColumns: zod.union([zod.boolean(), zod.null()]).optional(),
    sessionIdPushdown: zod
        .union([zod.boolean(), zod.null()])
        .optional()
        .describe(
            'Push a `session_id_v7 IN (SELECT … FROM events WHERE …)` predicate into the raw_sessions subquery to limit aggregation to sessions that participate in the outer events filter.'
        ),
    sessionPropertyPreAggregation: zod
        .union([zod.boolean(), zod.null()])
        .optional()
        .describe(
            'Pre-filter raw_sessions aggregation by `session_id_v7 IN (cheap pre-aggregation that only materializes the columns referenced by the outer-WHERE session predicate)`. Useful when the breakdown\/SELECT pulls in many session columns (e.g. `$channel_type`) but the filter only references one (e.g. `$entry_current_url`).'
        ),
    sessionTableVersion: zod.union([SessionTableVersionApi, zod.null()]).optional(),
    sessionsV2JoinMode: zod.union([SessionsV2JoinModeApi, zod.null()]).optional(),
    timings: zod.union([zod.boolean(), zod.null()]).optional(),
    typeAwareCastSimplification: zod
        .union([zod.boolean(), zod.null()])
        .optional()
        .describe(
            'Remove provably redundant casts and nullability wrappers (e.g. `toString(String)`, `assumeNotNull(non_nullable)`, dead `ifNull` fallbacks) using inferred expression types'
        ),
    useMaterializedViews: zod.union([zod.boolean(), zod.null()]).optional(),
    usePreaggregatedIntermediateResults: zod.union([zod.boolean(), zod.null()]).optional(),
    usePreaggregatedTableTransforms: zod
        .union([zod.boolean(), zod.null()])
        .optional()
        .describe('Try to automatically convert HogQL queries to use preaggregated tables at the AST level \*'),
    useWebAnalyticsPreAggregatedTables: zod.union([zod.boolean(), zod.null()]).optional(),
})

export type HogQLQueryModifiersApi = zod.input<typeof HogQLQueryModifiersApi>
export type HogQLQueryModifiersApiOutput = zod.output<typeof HogQLQueryModifiersApi>

export const HogQueryResponseApi = zod.object({
    bytecode: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    coloredBytecode: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    results: zod.unknown(),
    stdout: zod.union([zod.string(), zod.null()]).optional(),
})

export type HogQueryResponseApi = zod.input<typeof HogQueryResponseApi>
export type HogQueryResponseApiOutput = zod.output<typeof HogQueryResponseApi>

export const QueryLogTagsApi = zod.object({
    name: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe('Name of the query, preferably unique. For example web_analytics_vitals'),
    productKey: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe(
            "Product responsible for this query. Use string, there's no need to churn the Schema when we add a new product \*"
        ),
    scene: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe(
            "Scene where this query is shown in the UI. Use string, there's no need to churn the Schema when we add a new Scene \*"
        ),
})

export type QueryLogTagsApi = zod.input<typeof QueryLogTagsApi>
export type QueryLogTagsApiOutput = zod.output<typeof QueryLogTagsApi>

export const hogQueryApiKindDefault = `HogQuery`

export const HogQueryApi = zod.object({
    code: zod.union([zod.string(), zod.null()]).optional(),
    kind: zod.literal('HogQuery').default(hogQueryApiKindDefault),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    response: zod.union([HogQueryResponseApi, zod.null()]).optional(),
    tags: zod.union([QueryLogTagsApi, zod.null()]).optional(),
    version: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('version of the node, used for schema migrations'),
})

export type HogQueryApi = zod.input<typeof HogQueryApi>
export type HogQueryApiOutput = zod.output<typeof HogQueryApi>

export const DashboardFilterApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type DashboardFilterApi = zod.input<typeof DashboardFilterApi>
export type DashboardFilterApiOutput = zod.output<typeof DashboardFilterApi>

export const TileFiltersApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type TileFiltersApi = zod.input<typeof TileFiltersApi>
export type TileFiltersApiOutput = zod.output<typeof TileFiltersApi>

export const ActivityEventsListWidgetTypeEnumApi = zod
    .enum(['activity_events_list'])
    .describe('\* `activity_events_list` - activity_events_list')

export type ActivityEventsListWidgetTypeEnumApi = zod.input<typeof ActivityEventsListWidgetTypeEnumApi>
export type ActivityEventsListWidgetTypeEnumApiOutput = zod.output<typeof ActivityEventsListWidgetTypeEnumApi>

export const ErrorTrackingListWidgetTypeEnumApi = zod
    .enum(['error_tracking_list'])
    .describe('\* `error_tracking_list` - error_tracking_list')

export type ErrorTrackingListWidgetTypeEnumApi = zod.input<typeof ErrorTrackingListWidgetTypeEnumApi>
export type ErrorTrackingListWidgetTypeEnumApiOutput = zod.output<typeof ErrorTrackingListWidgetTypeEnumApi>

export const SessionReplayListWidgetTypeEnumApi = zod
    .enum(['session_replay_list'])
    .describe('\* `session_replay_list` - session_replay_list')

export type SessionReplayListWidgetTypeEnumApi = zod.input<typeof SessionReplayListWidgetTypeEnumApi>
export type SessionReplayListWidgetTypeEnumApiOutput = zod.output<typeof SessionReplayListWidgetTypeEnumApi>

export const ExperimentsListWidgetTypeEnumApi = zod
    .enum(['experiments_list'])
    .describe('\* `experiments_list` - experiments_list')

export type ExperimentsListWidgetTypeEnumApi = zod.input<typeof ExperimentsListWidgetTypeEnumApi>
export type ExperimentsListWidgetTypeEnumApiOutput = zod.output<typeof ExperimentsListWidgetTypeEnumApi>

export const ExperimentResultsWidgetTypeEnumApi = zod
    .enum(['experiment_results'])
    .describe('\* `experiment_results` - experiment_results')

export type ExperimentResultsWidgetTypeEnumApi = zod.input<typeof ExperimentResultsWidgetTypeEnumApi>
export type ExperimentResultsWidgetTypeEnumApiOutput = zod.output<typeof ExperimentResultsWidgetTypeEnumApi>

export const SurveyResultsWidgetTypeEnumApi = zod
    .enum(['survey_results'])
    .describe('\* `survey_results` - survey_results')

export type SurveyResultsWidgetTypeEnumApi = zod.input<typeof SurveyResultsWidgetTypeEnumApi>
export type SurveyResultsWidgetTypeEnumApiOutput = zod.output<typeof SurveyResultsWidgetTypeEnumApi>

export const LogsListWidgetTypeEnumApi = zod.enum(['logs_list']).describe('\* `logs_list` - logs_list')

export type LogsListWidgetTypeEnumApi = zod.input<typeof LogsListWidgetTypeEnumApi>
export type LogsListWidgetTypeEnumApiOutput = zod.output<typeof LogsListWidgetTypeEnumApi>

export const TrendsQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type TrendsQueryApi = zod.input<typeof TrendsQueryApi>
export type TrendsQueryApiOutput = zod.output<typeof TrendsQueryApi>

export const FunnelsQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type FunnelsQueryApi = zod.input<typeof FunnelsQueryApi>
export type FunnelsQueryApiOutput = zod.output<typeof FunnelsQueryApi>

export const RetentionQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type RetentionQueryApi = zod.input<typeof RetentionQueryApi>
export type RetentionQueryApiOutput = zod.output<typeof RetentionQueryApi>

export const PathsQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type PathsQueryApi = zod.input<typeof PathsQueryApi>
export type PathsQueryApiOutput = zod.output<typeof PathsQueryApi>

export const StickinessQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type StickinessQueryApi = zod.input<typeof StickinessQueryApi>
export type StickinessQueryApiOutput = zod.output<typeof StickinessQueryApi>

export const LifecycleQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type LifecycleQueryApi = zod.input<typeof LifecycleQueryApi>
export type LifecycleQueryApiOutput = zod.output<typeof LifecycleQueryApi>

export const WebStatsTableQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type WebStatsTableQueryApi = zod.input<typeof WebStatsTableQueryApi>
export type WebStatsTableQueryApiOutput = zod.output<typeof WebStatsTableQueryApi>

export const WebOverviewQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type WebOverviewQueryApi = zod.input<typeof WebOverviewQueryApi>
export type WebOverviewQueryApiOutput = zod.output<typeof WebOverviewQueryApi>

export const ActionsPieApi = zod.object({
    disableHoverOffset: zod.union([zod.boolean(), zod.null()]).optional(),
    hideAggregation: zod.union([zod.boolean(), zod.null()]).optional(),
})

export type ActionsPieApi = zod.input<typeof ActionsPieApi>
export type ActionsPieApiOutput = zod.output<typeof ActionsPieApi>

export const RetentionApi = zod.object({
    hideLineGraph: zod.union([zod.boolean(), zod.null()]).optional(),
    hideSizeColumn: zod.union([zod.boolean(), zod.null()]).optional(),
    useSmallLayout: zod.union([zod.boolean(), zod.null()]).optional(),
})

export type RetentionApi = zod.input<typeof RetentionApi>
export type RetentionApiOutput = zod.output<typeof RetentionApi>

export const VizSpecificOptionsApi = zod.object({
    ActionsPie: zod.union([ActionsPieApi, zod.null()]).optional(),
    RETENTION: zod.union([RetentionApi, zod.null()]).optional(),
})

export type VizSpecificOptionsApi = zod.input<typeof VizSpecificOptionsApi>
export type VizSpecificOptionsApiOutput = zod.output<typeof VizSpecificOptionsApi>

export const DataTableNodeViewPropsContextTypeApi = zod.enum(['event_definition', 'team_columns'])

export type DataTableNodeViewPropsContextTypeApi = zod.input<typeof DataTableNodeViewPropsContextTypeApi>
export type DataTableNodeViewPropsContextTypeApiOutput = zod.output<typeof DataTableNodeViewPropsContextTypeApi>

export const DataTableNodeViewPropsContextApi = zod.object({
    eventDefinitionId: zod.union([zod.string(), zod.null()]).optional(),
    type: DataTableNodeViewPropsContextTypeApi,
})

export type DataTableNodeViewPropsContextApi = zod.input<typeof DataTableNodeViewPropsContextApi>
export type DataTableNodeViewPropsContextApiOutput = zod.output<typeof DataTableNodeViewPropsContextApi>

export const ClickhouseQueryProgressApi = zod.object({
    active_cpu_time: zod.number(),
    bytes_read: zod.number(),
    estimated_rows_total: zod.number(),
    rows_read: zod.number(),
    time_elapsed: zod.number(),
})

export type ClickhouseQueryProgressApi = zod.input<typeof ClickhouseQueryProgressApi>
export type ClickhouseQueryProgressApiOutput = zod.output<typeof ClickhouseQueryProgressApi>

export const queryStatusApiCompleteDefault = false
export const queryStatusApiErrorDefault = false
export const queryStatusApiQueryAsyncDefault = true

export const QueryStatusApi = zod.object({
    complete: zod
        .union([zod.boolean(), zod.null()])
        .default(queryStatusApiCompleteDefault)
        .describe(
            'Whether the query is still running. Will be true if the query is complete, even if it errored. Either result or error will be set.'
        ),
    dashboard_id: zod.union([zod.number(), zod.null()]).optional(),
    end_time: zod
        .union([zod.iso.datetime({ offset: true }), zod.null()])
        .optional()
        .describe('When did the query execution task finish (whether successfully or not).'),
    error: zod
        .union([zod.boolean(), zod.null()])
        .default(queryStatusApiErrorDefault)
        .describe(
            'If the query failed, this will be set to true. More information can be found in the error_message field.'
        ),
    error_code: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe('Stable machine-readable code for the error (the DRF exception code), when known.'),
    error_message: zod.union([zod.string(), zod.null()]).optional(),
    expiration_time: zod.union([zod.iso.datetime({ offset: true }), zod.null()]).optional(),
    id: zod.string(),
    insight_id: zod.union([zod.number(), zod.null()]).optional(),
    labels: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    pickup_time: zod
        .union([zod.iso.datetime({ offset: true }), zod.null()])
        .optional()
        .describe('When was the query execution task picked up by a worker.'),
    query_async: zod.boolean().default(queryStatusApiQueryAsyncDefault).describe('ONLY async queries use QueryStatus.'),
    query_progress: zod.union([ClickhouseQueryProgressApi, zod.null()]).optional(),
    results: zod.unknown().optional(),
    start_time: zod
        .union([zod.iso.datetime({ offset: true }), zod.null()])
        .optional()
        .describe('When was query execution task enqueued.'),
    task_id: zod.union([zod.string(), zod.null()]).optional(),
    team_id: zod.number(),
})

export type QueryStatusApi = zod.input<typeof QueryStatusApi>
export type QueryStatusApiOutput = zod.output<typeof QueryStatusApi>

export const ResolvedDateRangeResponseApi = zod.object({
    date_from: zod.iso.datetime({ offset: true }),
    date_to: zod.iso.datetime({ offset: true }),
})

export type ResolvedDateRangeResponseApi = zod.input<typeof ResolvedDateRangeResponseApi>
export type ResolvedDateRangeResponseApiOutput = zod.output<typeof ResolvedDateRangeResponseApi>

export const QueryTimingApi = zod.object({
    k: zod.string().describe("Key. Shortened to 'k' to save on data."),
    t: zod.number().describe("Time in seconds. Shortened to 't' to save on data."),
})

export type QueryTimingApi = zod.input<typeof QueryTimingApi>
export type QueryTimingApiOutput = zod.output<typeof QueryTimingApi>

export const DataWarehouseSourceUsageApi = zod.object({
    id: zod.string().describe('ExternalDataSource id'),
    source_type: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe('Connector type of the source (e.g. Stripe, Postgres), if known'),
    table_name: zod.string().describe('Warehouse table name that was referenced'),
})

export type DataWarehouseSourceUsageApi = zod.input<typeof DataWarehouseSourceUsageApi>
export type DataWarehouseSourceUsageApiOutput = zod.output<typeof DataWarehouseSourceUsageApi>

export const dataWarehouseSyncWarningApiTypeDefault = `warehouse_sync`

export const DataWarehouseSyncWarningApi = zod.object({
    message: zod.string().describe('Human-readable warning shown to the user'),
    schema_name: zod.string().describe('Name of the ExternalDataSchema responsible for syncing the table'),
    source_id: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe('ID of the ExternalDataSource, used to link to its management page. Null for self-managed tables.'),
    source_type: zod.string().describe('Source type, e.g. \"Stripe\", \"Hubspot\"'),
    status: zod
        .string()
        .describe('Sync status that triggered the warning, e.g. \"Failed\", \"Paused\", \"BillingLimitReached\"'),
    table_name: zod.string().describe('Name of the warehouse table the warning refers to'),
    type: zod
        .literal('warehouse_sync')
        .default(dataWarehouseSyncWarningApiTypeDefault)
        .describe('Tells warning kinds apart in the shared `warnings` list'),
})

export type DataWarehouseSyncWarningApi = zod.input<typeof DataWarehouseSyncWarningApi>
export type DataWarehouseSyncWarningApiOutput = zod.output<typeof DataWarehouseSyncWarningApi>

export const accessControlFilterWarningApiTypeDefault = `access_control`

export const AccessControlFilterWarningApi = zod.object({
    message: zod.string().describe('Human-readable warning shown to the user'),
    resources: zod
        .array(zod.string())
        .describe(
            'Resource types the user has access restrictions on, referenced by the query, e.g. [\"insight\", \"dashboard\"]'
        ),
    type: zod
        .literal('access_control')
        .default(accessControlFilterWarningApiTypeDefault)
        .describe('Tells warning kinds apart in the shared `warnings` list'),
})

export type AccessControlFilterWarningApi = zod.input<typeof AccessControlFilterWarningApi>
export type AccessControlFilterWarningApiOutput = zod.output<typeof AccessControlFilterWarningApi>

export const ResponseApi = zod.object({
    columns: zod.array(zod.unknown()),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.string().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    nextCursor: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe('Cursor for fetching the next page of results'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.array(zod.unknown())),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.array(zod.string()),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type ResponseApi = zod.input<typeof ResponseApi>
export type ResponseApiOutput = zod.output<typeof ResponseApi>

export const Response1Api = zod.object({
    columns: zod.array(zod.unknown()),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.string().describe('Generated HogQL query.'),
    limit: zod.number(),
    missing_actors_count: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.number(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.array(zod.unknown())),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response1Api = zod.input<typeof Response1Api>
export type Response1ApiOutput = zod.output<typeof Response1Api>

export const response2ApiKindDefault = `GroupsQuery`

export const Response2Api = zod.object({
    columns: zod.array(zod.unknown()),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.string().describe('Generated HogQL query.'),
    kind: zod.literal('GroupsQuery').default(response2ApiKindDefault),
    limit: zod.number(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.number(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.array(zod.unknown())),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.array(zod.string()),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response2Api = zod.input<typeof Response2Api>
export type Response2ApiOutput = zod.output<typeof Response2Api>

export const HogQLNoticeApi = zod.object({
    end: zod.union([zod.number(), zod.null()]).optional(),
    fix: zod.union([zod.string(), zod.null()]).optional(),
    message: zod.string(),
    start: zod.union([zod.number(), zod.null()]).optional(),
})

export type HogQLNoticeApi = zod.input<typeof HogQLNoticeApi>
export type HogQLNoticeApiOutput = zod.output<typeof HogQLNoticeApi>

export const QueryIndexUsageApi = zod.enum(['undecisive', 'no', 'partial', 'yes'])

export type QueryIndexUsageApi = zod.input<typeof QueryIndexUsageApi>
export type QueryIndexUsageApiOutput = zod.output<typeof QueryIndexUsageApi>

export const HogQLMetadataResponseApi = zod.object({
    ch_table_names: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    errors: zod.array(HogQLNoticeApi),
    isUsingIndices: zod.union([QueryIndexUsageApi, zod.null()]).optional(),
    isValid: zod.union([zod.boolean(), zod.null()]).optional(),
    notices: zod.array(HogQLNoticeApi),
    query: zod.union([zod.string(), zod.null()]).optional(),
    table_names: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    warnings: zod.array(HogQLNoticeApi),
})

export type HogQLMetadataResponseApi = zod.input<typeof HogQLMetadataResponseApi>
export type HogQLMetadataResponseApiOutput = zod.output<typeof HogQLMetadataResponseApi>

export const Response3Api = zod.object({
    clickhouse: zod.union([zod.string(), zod.null()]).optional().describe('Executed ClickHouse query'),
    columns: zod
        .union([zod.array(zod.unknown()), zod.null()])
        .optional()
        .describe('Returned columns'),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    explain: zod
        .union([zod.array(zod.string()), zod.null()])
        .optional()
        .describe('Query explanation output'),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    metadata: zod.union([HogQLMetadataResponseApi, zod.null()]).optional().describe('Query metadata output'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query: zod.union([zod.string(), zod.null()]).optional().describe('Input query string'),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.unknown()),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod
        .union([zod.array(zod.unknown()), zod.null()])
        .optional()
        .describe('Types of returned columns'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response3Api = zod.input<typeof Response3Api>
export type Response3ApiOutput = zod.output<typeof Response3Api>

export const WebAnalyticsPreComputeStrategyApi = zod.enum(['pre_aggregated', 'lazy_precompute', 'live'])

export type WebAnalyticsPreComputeStrategyApi = zod.input<typeof WebAnalyticsPreComputeStrategyApi>
export type WebAnalyticsPreComputeStrategyApiOutput = zod.output<typeof WebAnalyticsPreComputeStrategyApi>

export const WebAnalyticsItemKindApi = zod.enum(['unit', 'duration_s', 'percentage', 'currency'])

export type WebAnalyticsItemKindApi = zod.input<typeof WebAnalyticsItemKindApi>
export type WebAnalyticsItemKindApiOutput = zod.output<typeof WebAnalyticsItemKindApi>

export const WebOverviewItemApi = zod.object({
    changeFromPreviousPct: zod.union([zod.number(), zod.null()]).optional(),
    isIncreaseBad: zod.union([zod.boolean(), zod.null()]).optional(),
    key: zod.string(),
    kind: WebAnalyticsItemKindApi,
    previous: zod.union([zod.number(), zod.null()]).optional(),
    value: zod.union([zod.number(), zod.null()]).optional(),
})

export type WebOverviewItemApi = zod.input<typeof WebOverviewItemApi>
export type WebOverviewItemApiOutput = zod.output<typeof WebOverviewItemApi>

export const SamplingRateApi = zod.object({
    denominator: zod.union([zod.number(), zod.null()]).optional(),
    numerator: zod.number(),
})

export type SamplingRateApi = zod.input<typeof SamplingRateApi>
export type SamplingRateApiOutput = zod.output<typeof SamplingRateApi>

export const Response4Api = zod.object({
    dateFrom: zod.union([zod.string(), zod.null()]).optional(),
    dateTo: zod.union([zod.string(), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    preComputeStrategy: zod.union([WebAnalyticsPreComputeStrategyApi, zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(WebOverviewItemApi),
    samplingRate: zod.union([SamplingRateApi, zod.null()]).optional(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response4Api = zod.input<typeof Response4Api>
export type Response4ApiOutput = zod.output<typeof Response4Api>

export const Response5Api = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    preComputeStale: zod
        .union([zod.boolean(), zod.null()])
        .optional()
        .describe(
            'Whether a lazy-precompute read was served from expired-within-grace (stale) jobs instead of recomputing inline.'
        ),
    preComputeStrategy: zod.union([WebAnalyticsPreComputeStrategyApi, zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.unknown()),
    samplingRate: zod.union([SamplingRateApi, zod.null()]).optional(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response5Api = zod.input<typeof Response5Api>
export type Response5ApiOutput = zod.output<typeof Response5Api>

export const Response6Api = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.unknown()),
    samplingRate: zod.union([SamplingRateApi, zod.null()]).optional(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response6Api = zod.input<typeof Response6Api>
export type Response6ApiOutput = zod.output<typeof Response6Api>

export const Response7Api = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.unknown()),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response7Api = zod.input<typeof Response7Api>
export type Response7ApiOutput = zod.output<typeof Response7Api>

export const Response8Api = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    preComputeStrategy: zod.union([WebAnalyticsPreComputeStrategyApi, zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.unknown()),
    samplingRate: zod.union([SamplingRateApi, zod.null()]).optional(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response8Api = zod.input<typeof Response8Api>
export type Response8ApiOutput = zod.output<typeof Response8Api>

export const WebVitalsPathBreakdownResultItemApi = zod.object({
    path: zod.string(),
    value: zod.number(),
})

export type WebVitalsPathBreakdownResultItemApi = zod.input<typeof WebVitalsPathBreakdownResultItemApi>
export type WebVitalsPathBreakdownResultItemApiOutput = zod.output<typeof WebVitalsPathBreakdownResultItemApi>

export const WebVitalsPathBreakdownResultApi = zod.object({
    good: zod.array(WebVitalsPathBreakdownResultItemApi),
    needs_improvements: zod.array(WebVitalsPathBreakdownResultItemApi),
    poor: zod.array(WebVitalsPathBreakdownResultItemApi),
})

export type WebVitalsPathBreakdownResultApi = zod.input<typeof WebVitalsPathBreakdownResultApi>
export type WebVitalsPathBreakdownResultApiOutput = zod.output<typeof WebVitalsPathBreakdownResultApi>

export const response9ApiResultsMax = 1

export const Response9Api = zod.object({
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    preComputeStrategy: zod.union([WebAnalyticsPreComputeStrategyApi, zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(WebVitalsPathBreakdownResultApi).min(1).max(response9ApiResultsMax),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response9Api = zod.input<typeof Response9Api>
export type Response9ApiOutput = zod.output<typeof Response9Api>

export const Response10Api = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.unknown(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response10Api = zod.input<typeof Response10Api>
export type Response10ApiOutput = zod.output<typeof Response10Api>

export const Response11Api = zod.object({
    columns: zod.array(zod.unknown()),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.string().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.array(zod.unknown())),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.array(zod.string()),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response11Api = zod.input<typeof Response11Api>
export type Response11ApiOutput = zod.output<typeof Response11Api>

export const MarketingAnalyticsItemApi = zod.object({
    changeFromPreviousPct: zod.union([zod.number(), zod.null()]).optional(),
    hasComparison: zod.union([zod.boolean(), zod.null()]).optional(),
    isIncreaseBad: zod.union([zod.boolean(), zod.null()]).optional(),
    key: zod.string(),
    kind: WebAnalyticsItemKindApi,
    previous: zod.union([zod.number(), zod.string(), zod.null()]).optional(),
    value: zod.union([zod.number(), zod.string(), zod.null()]).optional(),
})

export type MarketingAnalyticsItemApi = zod.input<typeof MarketingAnalyticsItemApi>
export type MarketingAnalyticsItemApiOutput = zod.output<typeof MarketingAnalyticsItemApi>

export const Response12Api = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.array(MarketingAnalyticsItemApi)),
    samplingRate: zod.union([SamplingRateApi, zod.null()]).optional(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response12Api = zod.input<typeof Response12Api>
export type Response12ApiOutput = zod.output<typeof Response12Api>

export const Response13Api = zod.object({
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.record(zod.string(), MarketingAnalyticsItemApi),
    samplingRate: zod.union([SamplingRateApi, zod.null()]).optional(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response13Api = zod.input<typeof Response13Api>
export type Response13ApiOutput = zod.output<typeof Response13Api>

export const Response14Api = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.array(MarketingAnalyticsItemApi)),
    samplingRate: zod.union([SamplingRateApi, zod.null()]).optional(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response14Api = zod.input<typeof Response14Api>
export type Response14ApiOutput = zod.output<typeof Response14Api>

export const VolumeBucketApi = zod.object({
    label: zod.string(),
    value: zod.number(),
})

export type VolumeBucketApi = zod.input<typeof VolumeBucketApi>
export type VolumeBucketApiOutput = zod.output<typeof VolumeBucketApi>

export const ErrorTrackingIssueAggregationsApi = zod.object({
    occurrences: zod.number(),
    sessions: zod.number(),
    users: zod.number(),
    volumeRange: zod.union([zod.array(zod.number()), zod.null()]).optional(),
    volume_buckets: zod.array(VolumeBucketApi),
})

export type ErrorTrackingIssueAggregationsApi = zod.input<typeof ErrorTrackingIssueAggregationsApi>
export type ErrorTrackingIssueAggregationsApiOutput = zod.output<typeof ErrorTrackingIssueAggregationsApi>

export const ErrorTrackingIssueAssigneeTypeApi = zod.enum(['user', 'role'])

export type ErrorTrackingIssueAssigneeTypeApi = zod.input<typeof ErrorTrackingIssueAssigneeTypeApi>
export type ErrorTrackingIssueAssigneeTypeApiOutput = zod.output<typeof ErrorTrackingIssueAssigneeTypeApi>

export const ErrorTrackingIssueAssigneeApi = zod.object({
    id: zod.union([zod.string(), zod.number()]),
    type: ErrorTrackingIssueAssigneeTypeApi,
})

export type ErrorTrackingIssueAssigneeApi = zod.input<typeof ErrorTrackingIssueAssigneeApi>
export type ErrorTrackingIssueAssigneeApiOutput = zod.output<typeof ErrorTrackingIssueAssigneeApi>

export const ErrorTrackingIssueCohortApi = zod.object({
    id: zod.number(),
    name: zod.string(),
})

export type ErrorTrackingIssueCohortApi = zod.input<typeof ErrorTrackingIssueCohortApi>
export type ErrorTrackingIssueCohortApiOutput = zod.output<typeof ErrorTrackingIssueCohortApi>

export const IntegrationKindApi = zod.enum([
    'slack',
    'salesforce',
    'hubspot',
    'google-pubsub',
    'google-cloud-service-account',
    'google-cloud-storage',
    'google-ads',
    'google-analytics',
    'google-search-console',
    'google-sheets',
    'linkedin-ads',
    'snapchat',
    'stripe',
    'intercom',
    'email',
    'twilio',
    'linear',
    'github',
    'gitlab',
    'meta-ads',
    'clickup',
    'reddit-ads',
    'databricks',
    'tiktok-ads',
    'bing-ads',
    'vercel',
    'azure-blob',
    'firebase',
    'jira',
    'pinterest-ads',
    'pardot',
    'customerio-app',
    'customerio-webhook',
    'customerio-track',
    'apns',
    'postgresql',
    'aws-s3',
    's3-compatible',
    'snowflake',
])

export type IntegrationKindApi = zod.input<typeof IntegrationKindApi>
export type IntegrationKindApiOutput = zod.output<typeof IntegrationKindApi>

export const ErrorTrackingExternalReferenceIntegrationApi = zod.object({
    display_name: zod.string(),
    id: zod.number(),
    kind: IntegrationKindApi,
})

export type ErrorTrackingExternalReferenceIntegrationApi = zod.input<
    typeof ErrorTrackingExternalReferenceIntegrationApi
>
export type ErrorTrackingExternalReferenceIntegrationApiOutput = zod.output<
    typeof ErrorTrackingExternalReferenceIntegrationApi
>

export const ErrorTrackingExternalReferenceApi = zod.object({
    external_url: zod.string(),
    id: zod.string(),
    integration: ErrorTrackingExternalReferenceIntegrationApi,
})

export type ErrorTrackingExternalReferenceApi = zod.input<typeof ErrorTrackingExternalReferenceApi>
export type ErrorTrackingExternalReferenceApiOutput = zod.output<typeof ErrorTrackingExternalReferenceApi>

export const FirstEventApi = zod.object({
    distinct_id: zod.string(),
    properties: zod.string(),
    timestamp: zod.string(),
    uuid: zod.string(),
})

export type FirstEventApi = zod.input<typeof FirstEventApi>
export type FirstEventApiOutput = zod.output<typeof FirstEventApi>

export const LastEventApi = zod.object({
    distinct_id: zod.string(),
    properties: zod.string(),
    timestamp: zod.string(),
    uuid: zod.string(),
})

export type LastEventApi = zod.input<typeof LastEventApi>
export type LastEventApiOutput = zod.output<typeof LastEventApi>

export const ErrorTrackingIssueStatusApi = zod.enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])

export type ErrorTrackingIssueStatusApi = zod.input<typeof ErrorTrackingIssueStatusApi>
export type ErrorTrackingIssueStatusApiOutput = zod.output<typeof ErrorTrackingIssueStatusApi>

export const ErrorTrackingIssueApi = zod.object({
    aggregations: zod.union([ErrorTrackingIssueAggregationsApi, zod.null()]).optional(),
    assignee: zod.union([ErrorTrackingIssueAssigneeApi, zod.null()]).optional(),
    cohort: zod.union([ErrorTrackingIssueCohortApi, zod.null()]).optional(),
    description: zod.union([zod.string(), zod.null()]).optional(),
    external_issues: zod.union([zod.array(ErrorTrackingExternalReferenceApi), zod.null()]).optional(),
    first_event: zod.union([FirstEventApi, zod.null()]).optional(),
    first_seen: zod.iso.datetime({ offset: true }),
    function: zod.union([zod.string(), zod.null()]).optional(),
    id: zod.string(),
    last_event: zod.union([LastEventApi, zod.null()]).optional(),
    last_seen: zod.iso.datetime({ offset: true }),
    library: zod.union([zod.string(), zod.null()]).optional(),
    name: zod.union([zod.string(), zod.null()]).optional(),
    source: zod.union([zod.string(), zod.null()]).optional(),
    status: ErrorTrackingIssueStatusApi,
})

export type ErrorTrackingIssueApi = zod.input<typeof ErrorTrackingIssueApi>
export type ErrorTrackingIssueApiOutput = zod.output<typeof ErrorTrackingIssueApi>

export const Response15Api = zod.object({
    columns: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(ErrorTrackingIssueApi),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response15Api = zod.input<typeof Response15Api>
export type Response15ApiOutput = zod.output<typeof Response15Api>

export const PopulationApi = zod.object({
    both: zod.number(),
    exception_only: zod.number(),
    neither: zod.number(),
    success_only: zod.number(),
})

export type PopulationApi = zod.input<typeof PopulationApi>
export type PopulationApiOutput = zod.output<typeof PopulationApi>

export const ErrorTrackingCorrelatedIssueApi = zod.object({
    assignee: zod.union([ErrorTrackingIssueAssigneeApi, zod.null()]).optional(),
    cohort: zod.union([ErrorTrackingIssueCohortApi, zod.null()]).optional(),
    description: zod.union([zod.string(), zod.null()]).optional(),
    event: zod.string(),
    external_issues: zod.union([zod.array(ErrorTrackingExternalReferenceApi), zod.null()]).optional(),
    first_seen: zod.iso.datetime({ offset: true }),
    id: zod.string(),
    last_seen: zod.iso.datetime({ offset: true }),
    library: zod.union([zod.string(), zod.null()]).optional(),
    name: zod.union([zod.string(), zod.null()]).optional(),
    odds_ratio: zod.number(),
    population: PopulationApi,
    status: ErrorTrackingIssueStatusApi,
})

export type ErrorTrackingCorrelatedIssueApi = zod.input<typeof ErrorTrackingCorrelatedIssueApi>
export type ErrorTrackingCorrelatedIssueApiOutput = zod.output<typeof ErrorTrackingCorrelatedIssueApi>

export const Response16Api = zod.object({
    columns: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(ErrorTrackingCorrelatedIssueApi),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response16Api = zod.input<typeof Response16Api>
export type Response16ApiOutput = zod.output<typeof Response16Api>

export const Response17Api = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type Response17Api = zod.input<typeof Response17Api>
export type Response17ApiOutput = zod.output<typeof Response17Api>

export const Response18Api = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type Response18Api = zod.input<typeof Response18Api>
export type Response18ApiOutput = zod.output<typeof Response18Api>

export const AIEventTypeApi = zod.enum([
    '$ai_generation',
    '$ai_embedding',
    '$ai_span',
    '$ai_trace',
    '$ai_metric',
    '$ai_feedback',
    '$ai_evaluation',
    '$ai_tag',
    '$ai_trace_summary',
    '$ai_generation_summary',
    '$ai_trace_clusters',
    '$ai_generation_clusters',
])

export type AIEventTypeApi = zod.input<typeof AIEventTypeApi>
export type AIEventTypeApiOutput = zod.output<typeof AIEventTypeApi>

export const LLMSentimentMessageApi = zod.object({
    label: zod.string(),
    score: zod.number(),
    scores: zod.union([zod.record(zod.string(), zod.number()), zod.null()]).optional(),
})

export type LLMSentimentMessageApi = zod.input<typeof LLMSentimentMessageApi>
export type LLMSentimentMessageApiOutput = zod.output<typeof LLMSentimentMessageApi>

export const LLMSentimentResultApi = zod.object({
    label: zod.string(),
    message_count: zod.union([zod.number(), zod.null()]).optional(),
    messages: zod.union([zod.record(zod.string(), LLMSentimentMessageApi), zod.null()]).optional(),
    score: zod.number(),
    scores: zod.union([zod.record(zod.string(), zod.number()), zod.null()]).optional(),
})

export type LLMSentimentResultApi = zod.input<typeof LLMSentimentResultApi>
export type LLMSentimentResultApiOutput = zod.output<typeof LLMSentimentResultApi>

export const LLMTraceEventApi = zod.object({
    createdAt: zod.string(),
    event: zod.union([AIEventTypeApi, zod.string()]),
    id: zod.string(),
    properties: zod.record(zod.string(), zod.unknown()),
    sentiment: zod.union([LLMSentimentResultApi, zod.null()]).optional(),
})

export type LLMTraceEventApi = zod.input<typeof LLMTraceEventApi>
export type LLMTraceEventApiOutput = zod.output<typeof LLMTraceEventApi>

export const LLMTracePersonApi = zod.object({
    created_at: zod.string(),
    distinct_id: zod.string(),
    properties: zod.record(zod.string(), zod.unknown()),
    uuid: zod.string(),
})

export type LLMTracePersonApi = zod.input<typeof LLMTracePersonApi>
export type LLMTracePersonApiOutput = zod.output<typeof LLMTracePersonApi>

export const LLMTraceApi = zod.object({
    aiSessionId: zod.union([zod.string(), zod.null()]).optional(),
    createdAt: zod.string(),
    distinctId: zod.string(),
    errorCount: zod.union([zod.number(), zod.null()]).optional(),
    events: zod.array(LLMTraceEventApi),
    id: zod.string(),
    inputCost: zod.union([zod.number(), zod.null()]).optional(),
    inputState: zod.unknown().optional(),
    inputTokens: zod.union([zod.number(), zod.null()]).optional(),
    isSupportTrace: zod.union([zod.boolean(), zod.null()]).optional(),
    outputCost: zod.union([zod.number(), zod.null()]).optional(),
    outputState: zod.unknown().optional(),
    outputTokens: zod.union([zod.number(), zod.null()]).optional(),
    person: zod.union([LLMTracePersonApi, zod.null()]).optional(),
    requestCost: zod.union([zod.number(), zod.null()]).optional(),
    sentiment: zod.union([LLMSentimentResultApi, zod.null()]).optional(),
    tools: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    totalCost: zod.union([zod.number(), zod.null()]).optional(),
    totalLatency: zod.union([zod.number(), zod.null()]).optional(),
    traceName: zod.union([zod.string(), zod.null()]).optional(),
    webSearchCost: zod.union([zod.number(), zod.null()]).optional(),
})

export type LLMTraceApi = zod.input<typeof LLMTraceApi>
export type LLMTraceApiOutput = zod.output<typeof LLMTraceApi>

export const Response19Api = zod.object({
    columns: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(LLMTraceApi),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response19Api = zod.input<typeof Response19Api>
export type Response19ApiOutput = zod.output<typeof Response19Api>

export const Response21Api = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.unknown()),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response21Api = zod.input<typeof Response21Api>
export type Response21ApiOutput = zod.output<typeof Response21Api>

export const response22ApiKindDefault = `AccountsQuery`

export const Response22Api = zod.object({
    columns: zod.array(zod.unknown()),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.string().describe('Generated HogQL query.'),
    kind: zod.literal('AccountsQuery').default(response22ApiKindDefault),
    limit: zod.number(),
    metricsResults: zod
        .union([zod.array(zod.union([zod.number(), zod.null()])), zod.null()])
        .optional()
        .describe('When `metrics` is set on the query, the aggregated values in the same order.'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.number(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.array(zod.unknown())),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.array(zod.string()),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type Response22Api = zod.input<typeof Response22Api>
export type Response22ApiOutput = zod.output<typeof Response22Api>

export const TaxonomicFilterGroupTypeApi = zod.enum([
    'metadata',
    'actions',
    'cohorts',
    'cohorts_with_all',
    'data_warehouse',
    'data_warehouse_source_tables',
    'data_warehouse_properties',
    'data_warehouse_person_properties',
    'elements',
    'events',
    'internal_events',
    'internal_event_properties',
    'event_properties',
    'event_feature_flags',
    'event_metadata',
    'numerical_event_properties',
    'person_properties',
    'person_metadata',
    'pageview_urls',
    'pageview_events',
    'screens',
    'screen_events',
    'email_addresses',
    'autocapture_events',
    'custom_events',
    'wildcard',
    'groups',
    'persons',
    'feature_flags',
    'insights',
    'experiments',
    'plugins',
    'dashboards',
    'name_groups',
    'session_properties',
    'hogql_expression',
    'notebooks',
    'log_entries',
    'error_tracking_issues',
    'logs',
    'log_attributes',
    'log_resource_attributes',
    'metric_attributes',
    'spans',
    'span_attributes',
    'span_resource_attributes',
    'replay',
    'replay_saved_filters',
    'revenue_analytics_properties',
    'account_custom_properties',
    'resources',
    'error_tracking_properties',
    'activity_log_properties',
    'mcp_properties',
    'max_ai_context',
    'workflow_variables',
    'suggested_filters',
    'recent_filters',
    'pinned_filters',
    'empty',
])

export type TaxonomicFilterGroupTypeApi = zod.input<typeof TaxonomicFilterGroupTypeApi>
export type TaxonomicFilterGroupTypeApiOutput = zod.output<typeof TaxonomicFilterGroupTypeApi>

export const EventsNodeApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type EventsNodeApi = zod.input<typeof EventsNodeApi>
export type EventsNodeApiOutput = zod.output<typeof EventsNodeApi>

export const EventsQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type EventsQueryApi = zod.input<typeof EventsQueryApi>
export type EventsQueryApiOutput = zod.output<typeof EventsQueryApi>

export const PersonsNodeApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type PersonsNodeApi = zod.input<typeof PersonsNodeApi>
export type PersonsNodeApiOutput = zod.output<typeof PersonsNodeApi>

export const ActorsQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ActorsQueryApi = zod.input<typeof ActorsQueryApi>
export type ActorsQueryApiOutput = zod.output<typeof ActorsQueryApi>

export const groupPropertyFilterApiTypeDefault = `group`

export const GroupPropertyFilterApi = zod.object({
    group_key_names: zod.union([zod.record(zod.string(), zod.string()), zod.null()]).optional(),
    group_type_index: zod.union([zod.number(), zod.null()]).optional(),
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('group').default(groupPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type GroupPropertyFilterApi = zod.input<typeof GroupPropertyFilterApi>
export type GroupPropertyFilterApiOutput = zod.output<typeof GroupPropertyFilterApi>

export const hogQLPropertyFilterApiTypeDefault = `hogql`

export const HogQLPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    type: zod.literal('hogql').default(hogQLPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type HogQLPropertyFilterApi = zod.input<typeof HogQLPropertyFilterApi>
export type HogQLPropertyFilterApiOutput = zod.output<typeof HogQLPropertyFilterApi>

export const groupsQueryResponseApiKindDefault = `GroupsQuery`

export const GroupsQueryResponseApi = zod.object({
    columns: zod.array(zod.unknown()),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.string().describe('Generated HogQL query.'),
    kind: zod.literal('GroupsQuery').default(groupsQueryResponseApiKindDefault),
    limit: zod.number(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.number(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.array(zod.unknown())),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.array(zod.string()),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type GroupsQueryResponseApi = zod.input<typeof GroupsQueryResponseApi>
export type GroupsQueryResponseApiOutput = zod.output<typeof GroupsQueryResponseApi>

export const groupsQueryApiKindDefault = `GroupsQuery`

export const GroupsQueryApi = zod.object({
    group_type_index: zod.number(),
    kind: zod.literal('GroupsQuery').default(groupsQueryApiKindDefault),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    orderBy: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    properties: zod
        .union([zod.array(zod.union([GroupPropertyFilterApi, HogQLPropertyFilterApi])), zod.null()])
        .optional(),
    response: zod.union([GroupsQueryResponseApi, zod.null()]).optional(),
    search: zod.union([zod.string(), zod.null()]).optional(),
    select: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    tags: zod.union([QueryLogTagsApi, zod.null()]).optional(),
    version: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('version of the node, used for schema migrations'),
})

export type GroupsQueryApi = zod.input<typeof GroupsQueryApi>
export type GroupsQueryApiOutput = zod.output<typeof GroupsQueryApi>

export const HogQLQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type HogQLQueryApi = zod.input<typeof HogQLQueryApi>
export type HogQLQueryApiOutput = zod.output<typeof HogQLQueryApi>

export const WebExternalClicksTableQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type WebExternalClicksTableQueryApi = zod.input<typeof WebExternalClicksTableQueryApi>
export type WebExternalClicksTableQueryApiOutput = zod.output<typeof WebExternalClicksTableQueryApi>

export const WebBotsTableQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type WebBotsTableQueryApi = zod.input<typeof WebBotsTableQueryApi>
export type WebBotsTableQueryApiOutput = zod.output<typeof WebBotsTableQueryApi>

export const WebGoalsQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type WebGoalsQueryApi = zod.input<typeof WebGoalsQueryApi>
export type WebGoalsQueryApiOutput = zod.output<typeof WebGoalsQueryApi>

export const WebVitalsQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type WebVitalsQueryApi = zod.input<typeof WebVitalsQueryApi>
export type WebVitalsQueryApiOutput = zod.output<typeof WebVitalsQueryApi>

export const WebVitalsPathBreakdownQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type WebVitalsPathBreakdownQueryApi = zod.input<typeof WebVitalsPathBreakdownQueryApi>
export type WebVitalsPathBreakdownQueryApiOutput = zod.output<typeof WebVitalsPathBreakdownQueryApi>

export const DaysOfWeekEnumApi = zod.union([
    zod.literal(1),
    zod.literal(2),
    zod.literal(3),
    zod.literal(4),
    zod.literal(5),
    zod.literal(6),
    zod.literal(7),
])

export type DaysOfWeekEnumApi = zod.input<typeof DaysOfWeekEnumApi>
export type DaysOfWeekEnumApiOutput = zod.output<typeof DaysOfWeekEnumApi>

export const dateRangeApiExcludeIncompletePeriodsDefault = false
export const dateRangeApiExplicitDateDefault = false

export const DateRangeApi = zod.object({
    date_from: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe(
            'Start of the date range. Accepts ISO 8601 timestamps (e.g., 2024-01-15T00:00:00Z) or relative formats: -7d (7 days ago), -2w (2 weeks ago), -1m (1 month ago),\n-1h (1 hour ago), -1mStart (start of last month), -1yStart (start of last year).'
        ),
    date_to: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe('End of the date range. Same format as date_from. Omit or null for \"now\".'),
    daysOfWeek: zod
        .union([zod.array(DaysOfWeekEnumApi), zod.null()])
        .optional()
        .describe(
            'Restrict the query to events occurring on these ISO days of week (1=Monday to 7=Sunday), evaluated in the project timezone. Omit or empty for all days. Only applied by insight queries.'
        ),
    excludeIncompletePeriods: zod
        .union([zod.boolean(), zod.null()])
        .default(dateRangeApiExcludeIncompletePeriodsDefault)
        .describe(
            'Exclude the current, still-collecting period by clipping date_to to the end of the last complete interval (evaluated in the project timezone). No-op when the range contains no complete interval. Only applied by insight queries.'
        ),
    explicitDate: zod
        .union([zod.boolean(), zod.null()])
        .default(dateRangeApiExplicitDateDefault)
        .describe(
            'Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of period.'
        ),
})

export type DateRangeApi = zod.input<typeof DateRangeApi>
export type DateRangeApiOutput = zod.output<typeof DateRangeApi>

export const sessionPropertyFilterApiTypeDefault = `session`

export const SessionPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('session').default(sessionPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type SessionPropertyFilterApi = zod.input<typeof SessionPropertyFilterApi>
export type SessionPropertyFilterApiOutput = zod.output<typeof SessionPropertyFilterApi>

export const FiltersApi = zod.object({
    dateRange: zod.union([DateRangeApi, zod.null()]).optional(),
    properties: zod.union([zod.array(SessionPropertyFilterApi), zod.null()]).optional(),
})

export type FiltersApi = zod.input<typeof FiltersApi>
export type FiltersApiOutput = zod.output<typeof FiltersApi>

export const SessionAttributionGroupByApi = zod.enum([
    'ChannelType',
    'Medium',
    'Source',
    'Campaign',
    'AdIds',
    'ReferringDomain',
    'InitialURL',
])

export type SessionAttributionGroupByApi = zod.input<typeof SessionAttributionGroupByApi>
export type SessionAttributionGroupByApiOutput = zod.output<typeof SessionAttributionGroupByApi>

export const SessionAttributionExplorerQueryResponseApi = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.unknown(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type SessionAttributionExplorerQueryResponseApi = zod.input<typeof SessionAttributionExplorerQueryResponseApi>
export type SessionAttributionExplorerQueryResponseApiOutput = zod.output<
    typeof SessionAttributionExplorerQueryResponseApi
>

export const sessionAttributionExplorerQueryApiKindDefault = `SessionAttributionExplorerQuery`

export const SessionAttributionExplorerQueryApi = zod.object({
    filters: zod.union([FiltersApi, zod.null()]).optional(),
    groupBy: zod.array(SessionAttributionGroupByApi),
    kind: zod.literal('SessionAttributionExplorerQuery').default(sessionAttributionExplorerQueryApiKindDefault),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    response: zod.union([SessionAttributionExplorerQueryResponseApi, zod.null()]).optional(),
    tags: zod.union([QueryLogTagsApi, zod.null()]).optional(),
    version: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('version of the node, used for schema migrations'),
})

export type SessionAttributionExplorerQueryApi = zod.input<typeof SessionAttributionExplorerQueryApi>
export type SessionAttributionExplorerQueryApiOutput = zod.output<typeof SessionAttributionExplorerQueryApi>

export const SessionsQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type SessionsQueryApi = zod.input<typeof SessionsQueryApi>
export type SessionsQueryApiOutput = zod.output<typeof SessionsQueryApi>

export const MarketingAnalyticsTableQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type MarketingAnalyticsTableQueryApi = zod.input<typeof MarketingAnalyticsTableQueryApi>
export type MarketingAnalyticsTableQueryApiOutput = zod.output<typeof MarketingAnalyticsTableQueryApi>

export const MarketingAnalyticsAggregatedQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type MarketingAnalyticsAggregatedQueryApi = zod.input<typeof MarketingAnalyticsAggregatedQueryApi>
export type MarketingAnalyticsAggregatedQueryApiOutput = zod.output<typeof MarketingAnalyticsAggregatedQueryApi>

export const NonIntegratedConversionsTableQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type NonIntegratedConversionsTableQueryApi = zod.input<typeof NonIntegratedConversionsTableQueryApi>
export type NonIntegratedConversionsTableQueryApiOutput = zod.output<typeof NonIntegratedConversionsTableQueryApi>

export const ErrorTrackingQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ErrorTrackingQueryApi = zod.input<typeof ErrorTrackingQueryApi>
export type ErrorTrackingQueryApiOutput = zod.output<typeof ErrorTrackingQueryApi>

export const ErrorTrackingIssueCorrelationQueryResponseApi = zod.object({
    columns: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(ErrorTrackingCorrelatedIssueApi),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type ErrorTrackingIssueCorrelationQueryResponseApi = zod.input<
    typeof ErrorTrackingIssueCorrelationQueryResponseApi
>
export type ErrorTrackingIssueCorrelationQueryResponseApiOutput = zod.output<
    typeof ErrorTrackingIssueCorrelationQueryResponseApi
>

export const errorTrackingIssueCorrelationQueryApiKindDefault = `ErrorTrackingIssueCorrelationQuery`

export const ErrorTrackingIssueCorrelationQueryApi = zod.object({
    events: zod.array(zod.string()),
    kind: zod.literal('ErrorTrackingIssueCorrelationQuery').default(errorTrackingIssueCorrelationQueryApiKindDefault),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    response: zod.union([ErrorTrackingIssueCorrelationQueryResponseApi, zod.null()]).optional(),
    tags: zod.union([QueryLogTagsApi, zod.null()]).optional(),
    version: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('version of the node, used for schema migrations'),
})

export type ErrorTrackingIssueCorrelationQueryApi = zod.input<typeof ErrorTrackingIssueCorrelationQueryApi>
export type ErrorTrackingIssueCorrelationQueryApiOutput = zod.output<typeof ErrorTrackingIssueCorrelationQueryApi>

export const ExperimentFunnelsQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentFunnelsQueryApi = zod.input<typeof ExperimentFunnelsQueryApi>
export type ExperimentFunnelsQueryApiOutput = zod.output<typeof ExperimentFunnelsQueryApi>

export const ExperimentTrendsQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentTrendsQueryApi = zod.input<typeof ExperimentTrendsQueryApi>
export type ExperimentTrendsQueryApiOutput = zod.output<typeof ExperimentTrendsQueryApi>

export const TracesQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type TracesQueryApi = zod.input<typeof TracesQueryApi>
export type TracesQueryApiOutput = zod.output<typeof TracesQueryApi>

export const TraceQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type TraceQueryApi = zod.input<typeof TraceQueryApi>
export type TraceQueryApiOutput = zod.output<typeof TraceQueryApi>

export const SessionQueryResponseApi = zod.object({
    columns: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(LLMTraceApi),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type SessionQueryResponseApi = zod.input<typeof SessionQueryResponseApi>
export type SessionQueryResponseApiOutput = zod.output<typeof SessionQueryResponseApi>

export const sessionQueryApiKindDefault = `SessionQuery`

export const SessionQueryApi = zod.object({
    dateRange: zod.union([DateRangeApi, zod.null()]).optional(),
    includeSentiment: zod
        .union([zod.boolean(), zod.null()])
        .optional()
        .describe('Include stored sentiment evaluation results for returned traces and generation events.'),
    kind: zod.literal('SessionQuery').default(sessionQueryApiKindDefault),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    response: zod.union([SessionQueryResponseApi, zod.null()]).optional(),
    sessionId: zod.string(),
    tags: zod.union([QueryLogTagsApi, zod.null()]).optional(),
    version: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('version of the node, used for schema migrations'),
})

export type SessionQueryApi = zod.input<typeof SessionQueryApi>
export type SessionQueryApiOutput = zod.output<typeof SessionQueryApi>

export const EndpointsUsageBreakdownApi = zod.enum(['Endpoint', 'MaterializationType', 'ApiKey', 'Status'])

export type EndpointsUsageBreakdownApi = zod.input<typeof EndpointsUsageBreakdownApi>
export type EndpointsUsageBreakdownApiOutput = zod.output<typeof EndpointsUsageBreakdownApi>

export const MaterializationTypeApi = zod.union([zod.literal('materialized'), zod.literal('inline'), zod.literal(null)])

export type MaterializationTypeApi = zod.input<typeof MaterializationTypeApi>
export type MaterializationTypeApiOutput = zod.output<typeof MaterializationTypeApi>

export const EndpointsUsageOrderByFieldApi = zod.enum([
    'requests',
    'bytes_read',
    'cpu_seconds',
    'avg_query_duration_ms',
    'error_rate',
])

export type EndpointsUsageOrderByFieldApi = zod.input<typeof EndpointsUsageOrderByFieldApi>
export type EndpointsUsageOrderByFieldApiOutput = zod.output<typeof EndpointsUsageOrderByFieldApi>

export const EndpointsUsageOrderByDirectionApi = zod.enum(['ASC', 'DESC'])

export type EndpointsUsageOrderByDirectionApi = zod.input<typeof EndpointsUsageOrderByDirectionApi>
export type EndpointsUsageOrderByDirectionApiOutput = zod.output<typeof EndpointsUsageOrderByDirectionApi>

export const EndpointsUsageTableQueryResponseApi = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.unknown()),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type EndpointsUsageTableQueryResponseApi = zod.input<typeof EndpointsUsageTableQueryResponseApi>
export type EndpointsUsageTableQueryResponseApiOutput = zod.output<typeof EndpointsUsageTableQueryResponseApi>

export const endpointsUsageTableQueryApiKindDefault = `EndpointsUsageTableQuery`

export const EndpointsUsageTableQueryApi = zod.object({
    breakdownBy: EndpointsUsageBreakdownApi,
    dateRange: zod.union([DateRangeApi, zod.null()]).optional(),
    endpointNames: zod
        .union([zod.array(zod.string()), zod.null()])
        .optional()
        .describe('Filter to specific endpoints by name'),
    kind: zod.literal('EndpointsUsageTableQuery').default(endpointsUsageTableQueryApiKindDefault),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    materializationType: zod
        .union([MaterializationTypeApi, zod.null()])
        .optional()
        .describe('Filter by materialization type'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    orderBy: zod
        .union([zod.array(zod.union([EndpointsUsageOrderByFieldApi, EndpointsUsageOrderByDirectionApi])), zod.null()])
        .optional(),
    response: zod.union([EndpointsUsageTableQueryResponseApi, zod.null()]).optional(),
    tags: zod.union([QueryLogTagsApi, zod.null()]).optional(),
    version: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('version of the node, used for schema migrations'),
})

export type EndpointsUsageTableQueryApi = zod.input<typeof EndpointsUsageTableQueryApi>
export type EndpointsUsageTableQueryApiOutput = zod.output<typeof EndpointsUsageTableQueryApi>

export const accountsQueryResponseApiKindDefault = `AccountsQuery`

export const AccountsQueryResponseApi = zod.object({
    columns: zod.array(zod.unknown()),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.string().describe('Generated HogQL query.'),
    kind: zod.literal('AccountsQuery').default(accountsQueryResponseApiKindDefault),
    limit: zod.number(),
    metricsResults: zod
        .union([zod.array(zod.union([zod.number(), zod.null()])), zod.null()])
        .optional()
        .describe('When `metrics` is set on the query, the aggregated values in the same order.'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.number(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.array(zod.unknown())),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.array(zod.string()),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type AccountsQueryResponseApi = zod.input<typeof AccountsQueryResponseApi>
export type AccountsQueryResponseApiOutput = zod.output<typeof AccountsQueryResponseApi>

export const accountsQueryApiKindDefault = `AccountsQuery`

export const AccountsQueryApi = zod.object({
    allRolesUnassigned: zod
        .union([zod.boolean(), zod.null()])
        .optional()
        .describe('Match accounts with no active relationship of any definition.'),
    assignedToUserIds: zod
        .union([zod.array(zod.number()), zod.null()])
        .optional()
        .describe(
            'Match accounts where any of these user ids actively holds any relationship (CSM, Account executive, or a custom definition). Drives the \"My accounts\" shortcut (the current user\'s id) and the shareable \"Assigned to\" filter — the ids are explicit so a shared URL resolves identically for every viewer.'
        ),
    filterExpression: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe(
            'Optional HogQL boolean expression AND-ed into the WHERE clause. Used by the overview tile click-to-filter affordance.'
        ),
    kind: zod.literal('AccountsQuery').default(accountsQueryApiKindDefault),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    metrics: zod
        .union([zod.array(zod.string()), zod.null()])
        .optional()
        .describe(
            'Aggregation expressions evaluated against the filtered account set; one value per metric is returned in `metricsResults`. When `metrics` is set without a `select`, the runner skips the regular row fetch and returns only the aggregated values.'
        ),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    orderBy: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    response: zod.union([AccountsQueryResponseApi, zod.null()]).optional(),
    search: zod.union([zod.string(), zod.null()]).optional(),
    select: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    tagNames: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    tags: zod.union([QueryLogTagsApi, zod.null()]).optional(),
    version: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('version of the node, used for schema migrations'),
})

export type AccountsQueryApi = zod.input<typeof AccountsQueryApi>
export type AccountsQueryApiOutput = zod.output<typeof AccountsQueryApi>

export const CurveApi = zod.enum(['linear', 'smooth'])

export type CurveApi = zod.input<typeof CurveApi>
export type CurveApiOutput = zod.output<typeof CurveApi>

export const ChartStyleApi = zod.object({
    curve: zod
        .union([CurveApi, zod.null()])
        .optional()
        .describe('Line interpolation: straight segments or a smoothed curve through the points.'),
})

export type ChartStyleApi = zod.input<typeof ChartStyleApi>
export type ChartStyleApiOutput = zod.output<typeof ChartStyleApi>

export const PositionApi = zod.enum(['start', 'end'])

export type PositionApi = zod.input<typeof PositionApi>
export type PositionApiOutput = zod.output<typeof PositionApi>

export const GoalLineApi = zod.object({
    borderColor: zod.union([zod.string(), zod.null()]).optional(),
    displayIfCrossed: zod.union([zod.boolean(), zod.null()]).optional(),
    displayLabel: zod.union([zod.boolean(), zod.null()]).optional(),
    label: zod.string(),
    position: zod.union([PositionApi, zod.null()]).optional(),
    value: zod.number(),
})

export type GoalLineApi = zod.input<typeof GoalLineApi>
export type GoalLineApiOutput = zod.output<typeof GoalLineApi>

export const HeatmapGradientStopApi = zod.object({
    color: zod.string(),
    value: zod.number(),
})

export type HeatmapGradientStopApi = zod.input<typeof HeatmapGradientStopApi>
export type HeatmapGradientStopApiOutput = zod.output<typeof HeatmapGradientStopApi>

export const GradientScaleModeApi = zod.enum(['absolute', 'relative'])

export type GradientScaleModeApi = zod.input<typeof GradientScaleModeApi>
export type GradientScaleModeApiOutput = zod.output<typeof GradientScaleModeApi>

export const HeatmapSortOrderApi = zod.enum(['asc', 'desc'])

export type HeatmapSortOrderApi = zod.input<typeof HeatmapSortOrderApi>
export type HeatmapSortOrderApiOutput = zod.output<typeof HeatmapSortOrderApi>

export const HeatmapSettingsApi = zod.object({
    gradient: zod.union([zod.array(HeatmapGradientStopApi), zod.null()]).optional(),
    gradientPreset: zod.union([zod.string(), zod.null()]).optional(),
    gradientScaleMode: zod.union([GradientScaleModeApi, zod.null()]).optional(),
    nullLabel: zod.union([zod.string(), zod.null()]).optional(),
    nullValue: zod.union([zod.string(), zod.null()]).optional(),
    sortColumn: zod.union([zod.string(), zod.null()]).optional(),
    sortOrder: zod.union([HeatmapSortOrderApi, zod.null()]).optional(),
    valueColumn: zod.union([zod.string(), zod.null()]).optional(),
    xAxisColumn: zod.union([zod.string(), zod.null()]).optional(),
    xAxisLabel: zod.union([zod.string(), zod.null()]).optional(),
    yAxisColumn: zod.union([zod.string(), zod.null()]).optional(),
    yAxisLabel: zod.union([zod.string(), zod.null()]).optional(),
})

export type HeatmapSettingsApi = zod.input<typeof HeatmapSettingsApi>
export type HeatmapSettingsApiOutput = zod.output<typeof HeatmapSettingsApi>

export const ScaleApi = zod.enum(['linear', 'logarithmic'])

export type ScaleApi = zod.input<typeof ScaleApi>
export type ScaleApiOutput = zod.output<typeof ScaleApi>

export const YAxisSettingsApi = zod.object({
    label: zod.union([zod.string(), zod.null()]).optional(),
    scale: zod.union([ScaleApi, zod.null()]).optional(),
    showGridLines: zod.union([zod.boolean(), zod.null()]).optional(),
    showTicks: zod.union([zod.boolean(), zod.null()]).optional(),
    startAtZero: zod.union([zod.boolean(), zod.null()]).optional().describe('Whether the Y axis should start at zero'),
})

export type YAxisSettingsApi = zod.input<typeof YAxisSettingsApi>
export type YAxisSettingsApiOutput = zod.output<typeof YAxisSettingsApi>

export const SliceContentApi = zod.enum(['labels', 'values', 'none'])

export type SliceContentApi = zod.input<typeof SliceContentApi>
export type SliceContentApiOutput = zod.output<typeof SliceContentApi>

export const ValueDisplayApi = zod.enum(['absolute', 'percentage'])

export type ValueDisplayApi = zod.input<typeof ValueDisplayApi>
export type ValueDisplayApiOutput = zod.output<typeof ValueDisplayApi>

export const PieChartSettingsApi = zod.object({
    showTotal: zod
        .union([zod.boolean(), zod.null()])
        .optional()
        .describe('Whether to show the aggregation total below the chart. Defaults to on.'),
    sliceContent: zod
        .union([SliceContentApi, zod.null()])
        .optional()
        .describe('What to render on each slice. Defaults to labels.'),
    valueDisplay: zod
        .union([ValueDisplayApi, zod.null()])
        .optional()
        .describe(
            'Whether slice values show as absolute amounts or shares of the total. Only applies when `sliceContent` is `values`.'
        ),
})

export type PieChartSettingsApi = zod.input<typeof PieChartSettingsApi>
export type PieChartSettingsApiOutput = zod.output<typeof PieChartSettingsApi>

export const DataColorTokenApi = zod.enum([
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
    'preset-11',
    'preset-12',
    'preset-13',
    'preset-14',
    'preset-15',
])

export type DataColorTokenApi = zod.input<typeof DataColorTokenApi>
export type DataColorTokenApiOutput = zod.output<typeof DataColorTokenApi>

export const resultCustomizationByValueApiAssignmentByDefault = `value`

export const ResultCustomizationByValueApi = zod.object({
    assignmentBy: zod.literal('value').default(resultCustomizationByValueApiAssignmentByDefault),
    color: zod.union([DataColorTokenApi, zod.null()]).optional(),
    hidden: zod.union([zod.boolean(), zod.null()]).optional(),
})

export type ResultCustomizationByValueApi = zod.input<typeof ResultCustomizationByValueApi>
export type ResultCustomizationByValueApiOutput = zod.output<typeof ResultCustomizationByValueApi>

export const DisplayTypeApi = zod.enum(['auto', 'line', 'bar', 'area'])

export type DisplayTypeApi = zod.input<typeof DisplayTypeApi>
export type DisplayTypeApiOutput = zod.output<typeof DisplayTypeApi>

export const YAxisPositionApi = zod.enum(['left', 'right'])

export type YAxisPositionApi = zod.input<typeof YAxisPositionApi>
export type YAxisPositionApiOutput = zod.output<typeof YAxisPositionApi>

export const ChartSettingsDisplayApi = zod.object({
    color: zod.union([zod.string(), zod.null()]).optional(),
    displayType: zod.union([DisplayTypeApi, zod.null()]).optional(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    trendLine: zod.union([zod.boolean(), zod.null()]).optional(),
    yAxisPosition: zod.union([YAxisPositionApi, zod.null()]).optional(),
})

export type ChartSettingsDisplayApi = zod.input<typeof ChartSettingsDisplayApi>
export type ChartSettingsDisplayApiOutput = zod.output<typeof ChartSettingsDisplayApi>

export const StyleApi = zod.enum(['none', 'number', 'short', 'percent'])

export type StyleApi = zod.input<typeof StyleApi>
export type StyleApiOutput = zod.output<typeof StyleApi>

export const ChartSettingsFormattingApi = zod.object({
    decimalPlaces: zod.union([zod.number(), zod.null()]).optional(),
    prefix: zod.union([zod.string(), zod.null()]).optional(),
    style: zod.union([StyleApi, zod.null()]).optional(),
    suffix: zod.union([zod.string(), zod.null()]).optional(),
})

export type ChartSettingsFormattingApi = zod.input<typeof ChartSettingsFormattingApi>
export type ChartSettingsFormattingApiOutput = zod.output<typeof ChartSettingsFormattingApi>

export const SettingsApi = zod.object({
    display: zod.union([ChartSettingsDisplayApi, zod.null()]).optional(),
    formatting: zod.union([ChartSettingsFormattingApi, zod.null()]).optional(),
})

export type SettingsApi = zod.input<typeof SettingsApi>
export type SettingsApiOutput = zod.output<typeof SettingsApi>

export const ChartAxisApi = zod.object({
    column: zod.string(),
    settings: zod.union([SettingsApi, zod.null()]).optional(),
})

export type ChartAxisApi = zod.input<typeof ChartAxisApi>
export type ChartAxisApiOutput = zod.output<typeof ChartAxisApi>

export const ChartSettingsApi = zod.object({
    chartStyle: zod
        .union([ChartStyleApi, zod.null()])
        .optional()
        .describe('Chart rendering style overrides (line shape). Only applies to line and area charts.'),
    goalLines: zod.union([zod.array(GoalLineApi), zod.null()]).optional(),
    heatmap: zod.union([HeatmapSettingsApi, zod.null()]).optional(),
    leftYAxisSettings: zod.union([YAxisSettingsApi, zod.null()]).optional(),
    pie: zod.union([PieChartSettingsApi, zod.null()]).optional(),
    resultCustomizations: zod
        .union([zod.record(zod.string(), ResultCustomizationByValueApi), zod.null()])
        .optional()
        .describe('Per-breakdown-value color customizations. Keyed by the raw breakdown column value.'),
    rightYAxisSettings: zod.union([YAxisSettingsApi, zod.null()]).optional(),
    seriesBreakdownColumn: zod.union([zod.string(), zod.null()]).optional(),
    showLegend: zod.union([zod.boolean(), zod.null()]).optional(),
    showNullsAsZero: zod.union([zod.boolean(), zod.null()]).optional(),
    showPieTotal: zod.union([zod.boolean(), zod.null()]).optional(),
    showTotalRow: zod.union([zod.boolean(), zod.null()]).optional(),
    showValuesOnSeries: zod.union([zod.boolean(), zod.null()]).optional(),
    showXAxisBorder: zod.union([zod.boolean(), zod.null()]).optional(),
    showXAxisTicks: zod.union([zod.boolean(), zod.null()]).optional(),
    showYAxisBorder: zod.union([zod.boolean(), zod.null()]).optional(),
    stackBars100: zod
        .union([zod.boolean(), zod.null()])
        .optional()
        .describe('Whether we fill the bars to 100% in stacked mode'),
    xAxis: zod.union([ChartAxisApi, zod.null()]).optional(),
    xAxisLabel: zod.union([zod.string(), zod.null()]).optional(),
    yAxis: zod.union([zod.array(ChartAxisApi), zod.null()]).optional(),
    yAxisAtZero: zod
        .union([zod.boolean(), zod.null()])
        .optional()
        .describe('Deprecated: use `[left|right]YAxisSettings`. Whether the Y axis should start at zero'),
})

export type ChartSettingsApi = zod.input<typeof ChartSettingsApi>
export type ChartSettingsApiOutput = zod.output<typeof ChartSettingsApi>

export const ChartDisplayTypeApi = zod.enum([
    'Auto',
    'ActionsLineGraph',
    'ActionsBar',
    'ActionsUnstackedBar',
    'ActionsStackedBar',
    'ActionsAreaGraph',
    'ActionsLineGraphCumulative',
    'BoldNumber',
    'Metric',
    'ActionsPie',
    'ActionsBarValue',
    'ActionsTable',
    'WorldMap',
    'CalendarHeatmap',
    'TwoDimensionalHeatmap',
    'BoxPlot',
    'SlopeGraph',
])

export type ChartDisplayTypeApi = zod.input<typeof ChartDisplayTypeApi>
export type ChartDisplayTypeApiOutput = zod.output<typeof ChartDisplayTypeApi>

export const ColorModeApi = zod.enum(['light', 'dark'])

export type ColorModeApi = zod.input<typeof ColorModeApi>
export type ColorModeApiOutput = zod.output<typeof ColorModeApi>

export const ConditionalFormattingRuleApi = zod.object({
    bytecode: zod.array(zod.unknown()),
    color: zod.string(),
    colorMode: zod.union([ColorModeApi, zod.null()]).optional(),
    columnName: zod.string(),
    id: zod.string(),
    input: zod.string(),
    templateId: zod.string(),
})

export type ConditionalFormattingRuleApi = zod.input<typeof ConditionalFormattingRuleApi>
export type ConditionalFormattingRuleApiOutput = zod.output<typeof ConditionalFormattingRuleApi>

export const TableSettingsApi = zod.object({
    columns: zod.union([zod.array(ChartAxisApi), zod.null()]).optional(),
    conditionalFormatting: zod.union([zod.array(ConditionalFormattingRuleApi), zod.null()]).optional(),
    pinnedColumns: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    transpose: zod.union([zod.boolean(), zod.null()]).optional(),
})

export type TableSettingsApi = zod.input<typeof TableSettingsApi>
export type TableSettingsApiOutput = zod.output<typeof TableSettingsApi>

export const BreakdownTypeApi = zod.enum([
    'cohort',
    'person',
    'event',
    'event_metadata',
    'group',
    'session',
    'hogql',
    'data_warehouse',
    'data_warehouse_person_property',
    'revenue_analytics',
])

export type BreakdownTypeApi = zod.input<typeof BreakdownTypeApi>
export type BreakdownTypeApiOutput = zod.output<typeof BreakdownTypeApi>

export const MultipleBreakdownTypeApi = zod.enum([
    'person',
    'event',
    'event_metadata',
    'group',
    'session',
    'hogql',
    'cohort',
    'revenue_analytics',
    'data_warehouse',
    'data_warehouse_person_property',
])

export type MultipleBreakdownTypeApi = zod.input<typeof MultipleBreakdownTypeApi>
export type MultipleBreakdownTypeApiOutput = zod.output<typeof MultipleBreakdownTypeApi>

export const BreakdownApi = zod.object({
    group_type_index: zod.union([zod.number(), zod.null()]).optional(),
    histogram_bin_count: zod.union([zod.number(), zod.null()]).optional(),
    normalize_url: zod.union([zod.boolean(), zod.null()]).optional(),
    property: zod.union([zod.string(), zod.number()]),
    type: zod.union([MultipleBreakdownTypeApi, zod.null()]).optional(),
})

export type BreakdownApi = zod.input<typeof BreakdownApi>
export type BreakdownApiOutput = zod.output<typeof BreakdownApi>

export const breakdownFilterApiBreakdownTypeDefault = `event`
export const breakdownFilterApiBreakdownsOneMax = 3

export const BreakdownFilterApi = zod.object({
    breakdown: zod
        .union([zod.string(), zod.array(zod.union([zod.string(), zod.number()])), zod.number(), zod.null()])
        .optional(),
    breakdown_group_type_index: zod.union([zod.number(), zod.null()]).optional(),
    breakdown_hide_other_aggregation: zod.union([zod.boolean(), zod.null()]).optional(),
    breakdown_histogram_bin_count: zod.union([zod.number(), zod.null()]).optional(),
    breakdown_limit: zod.union([zod.number(), zod.null()]).optional(),
    breakdown_normalize_url: zod.union([zod.boolean(), zod.null()]).optional(),
    breakdown_path_cleaning: zod.union([zod.boolean(), zod.null()]).optional(),
    breakdown_type: zod.union([BreakdownTypeApi, zod.null()]).default(breakdownFilterApiBreakdownTypeDefault),
    breakdowns: zod.union([zod.array(BreakdownApi).max(breakdownFilterApiBreakdownsOneMax), zod.null()]).optional(),
})

export type BreakdownFilterApi = zod.input<typeof BreakdownFilterApi>
export type BreakdownFilterApiOutput = zod.output<typeof BreakdownFilterApi>

export const IntervalTypeApi = zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month', 'quarter', 'year'])

export type IntervalTypeApi = zod.input<typeof IntervalTypeApi>
export type IntervalTypeApiOutput = zod.output<typeof IntervalTypeApi>

export const eventPropertyFilterApiOperatorDefault = `exact`
export const eventPropertyFilterApiTypeDefault = `event`

export const EventPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: zod.union([PropertyOperatorApi, zod.null()]).default(eventPropertyFilterApiOperatorDefault),
    type: zod.literal('event').default(eventPropertyFilterApiTypeDefault).describe('Event properties'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type EventPropertyFilterApi = zod.input<typeof EventPropertyFilterApi>
export type EventPropertyFilterApiOutput = zod.output<typeof EventPropertyFilterApi>

export const personPropertyFilterApiTypeDefault = `person`

export const PersonPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('person').default(personPropertyFilterApiTypeDefault).describe('Person properties'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type PersonPropertyFilterApi = zod.input<typeof PersonPropertyFilterApi>
export type PersonPropertyFilterApiOutput = zod.output<typeof PersonPropertyFilterApi>

export const personMetadataPropertyFilterApiTypeDefault = `person_metadata`

export const PersonMetadataPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod
        .literal('person_metadata')
        .default(personMetadataPropertyFilterApiTypeDefault)
        .describe('Top-level columns on the persons table (e.g. created_at), not properties JSON'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type PersonMetadataPropertyFilterApi = zod.input<typeof PersonMetadataPropertyFilterApi>
export type PersonMetadataPropertyFilterApiOutput = zod.output<typeof PersonMetadataPropertyFilterApi>

export const Key10Api = zod.enum(['tag_name', 'text', 'href', 'selector'])

export type Key10Api = zod.input<typeof Key10Api>
export type Key10ApiOutput = zod.output<typeof Key10Api>

export const elementPropertyFilterApiTypeDefault = `element`

export const ElementPropertyFilterApi = zod.object({
    key: Key10Api,
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('element').default(elementPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type ElementPropertyFilterApi = zod.input<typeof ElementPropertyFilterApi>
export type ElementPropertyFilterApiOutput = zod.output<typeof ElementPropertyFilterApi>

export const eventMetadataPropertyFilterApiTypeDefault = `event_metadata`

export const EventMetadataPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('event_metadata').default(eventMetadataPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type EventMetadataPropertyFilterApi = zod.input<typeof EventMetadataPropertyFilterApi>
export type EventMetadataPropertyFilterApiOutput = zod.output<typeof EventMetadataPropertyFilterApi>

export const cohortPropertyFilterApiKeyDefault = `id`
export const cohortPropertyFilterApiOperatorDefault = `in`
export const cohortPropertyFilterApiTypeDefault = `cohort`

export const CohortPropertyFilterApi = zod.object({
    cohort_name: zod.union([zod.string(), zod.null()]).optional(),
    key: zod.literal('id').default(cohortPropertyFilterApiKeyDefault),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: zod.union([PropertyOperatorApi, zod.null()]).default(cohortPropertyFilterApiOperatorDefault),
    type: zod.literal('cohort').default(cohortPropertyFilterApiTypeDefault),
    value: zod.number(),
})

export type CohortPropertyFilterApi = zod.input<typeof CohortPropertyFilterApi>
export type CohortPropertyFilterApiOutput = zod.output<typeof CohortPropertyFilterApi>

export const DurationTypeApi = zod.enum(['duration', 'active_seconds', 'inactive_seconds'])

export type DurationTypeApi = zod.input<typeof DurationTypeApi>
export type DurationTypeApiOutput = zod.output<typeof DurationTypeApi>

export const recordingPropertyFilterApiTypeDefault = `recording`

export const RecordingPropertyFilterApi = zod.object({
    key: zod.union([DurationTypeApi, zod.string()]),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('recording').default(recordingPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type RecordingPropertyFilterApi = zod.input<typeof RecordingPropertyFilterApi>
export type RecordingPropertyFilterApiOutput = zod.output<typeof RecordingPropertyFilterApi>

export const logEntryPropertyFilterApiTypeDefault = `log_entry`

export const LogEntryPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('log_entry').default(logEntryPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type LogEntryPropertyFilterApi = zod.input<typeof LogEntryPropertyFilterApi>
export type LogEntryPropertyFilterApiOutput = zod.output<typeof LogEntryPropertyFilterApi>

export const featurePropertyFilterApiTypeDefault = `feature`

export const FeaturePropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod
        .literal('feature')
        .default(featurePropertyFilterApiTypeDefault)
        .describe('Event property with \"$feature\/\" prepended'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type FeaturePropertyFilterApi = zod.input<typeof FeaturePropertyFilterApi>
export type FeaturePropertyFilterApiOutput = zod.output<typeof FeaturePropertyFilterApi>

export const flagPropertyFilterApiOperatorDefault = `flag_evaluates_to`
export const flagPropertyFilterApiTypeDefault = `flag`

export const FlagPropertyFilterApi = zod.object({
    key: zod.string().describe('The key should be the flag ID'),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: zod
        .literal('flag_evaluates_to')
        .default(flagPropertyFilterApiOperatorDefault)
        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
    type: zod.literal('flag').default(flagPropertyFilterApiTypeDefault).describe('Feature flag dependency'),
    value: zod.union([zod.boolean(), zod.string()]).describe('The value can be true, false, or a variant name'),
})

export type FlagPropertyFilterApi = zod.input<typeof FlagPropertyFilterApi>
export type FlagPropertyFilterApiOutput = zod.output<typeof FlagPropertyFilterApi>

export const emptyPropertyFilterApiTypeDefault = `empty`

export const EmptyPropertyFilterApi = zod.object({
    type: zod.literal('empty').default(emptyPropertyFilterApiTypeDefault),
})

export type EmptyPropertyFilterApi = zod.input<typeof EmptyPropertyFilterApi>
export type EmptyPropertyFilterApiOutput = zod.output<typeof EmptyPropertyFilterApi>

export const dataWarehousePropertyFilterApiTypeDefault = `data_warehouse`

export const DataWarehousePropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('data_warehouse').default(dataWarehousePropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type DataWarehousePropertyFilterApi = zod.input<typeof DataWarehousePropertyFilterApi>
export type DataWarehousePropertyFilterApiOutput = zod.output<typeof DataWarehousePropertyFilterApi>

export const dataWarehousePersonPropertyFilterApiTypeDefault = `data_warehouse_person_property`

export const DataWarehousePersonPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('data_warehouse_person_property').default(dataWarehousePersonPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type DataWarehousePersonPropertyFilterApi = zod.input<typeof DataWarehousePersonPropertyFilterApi>
export type DataWarehousePersonPropertyFilterApiOutput = zod.output<typeof DataWarehousePersonPropertyFilterApi>

export const errorTrackingIssueFilterApiTypeDefault = `error_tracking_issue`

export const ErrorTrackingIssueFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('error_tracking_issue').default(errorTrackingIssueFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type ErrorTrackingIssueFilterApi = zod.input<typeof ErrorTrackingIssueFilterApi>
export type ErrorTrackingIssueFilterApiOutput = zod.output<typeof ErrorTrackingIssueFilterApi>

export const LogPropertyFilterTypeApi = zod.enum(['log', 'log_attribute', 'log_resource_attribute'])

export type LogPropertyFilterTypeApi = zod.input<typeof LogPropertyFilterTypeApi>
export type LogPropertyFilterTypeApiOutput = zod.output<typeof LogPropertyFilterTypeApi>

export const LogPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: LogPropertyFilterTypeApi,
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type LogPropertyFilterApi = zod.input<typeof LogPropertyFilterApi>
export type LogPropertyFilterApiOutput = zod.output<typeof LogPropertyFilterApi>

export const metricPropertyFilterApiTypeDefault = `metric_attribute`

export const MetricPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('metric_attribute').default(metricPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type MetricPropertyFilterApi = zod.input<typeof MetricPropertyFilterApi>
export type MetricPropertyFilterApiOutput = zod.output<typeof MetricPropertyFilterApi>

export const SpanPropertyFilterTypeApi = zod.enum(['span', 'span_attribute', 'span_resource_attribute'])

export type SpanPropertyFilterTypeApi = zod.input<typeof SpanPropertyFilterTypeApi>
export type SpanPropertyFilterTypeApiOutput = zod.output<typeof SpanPropertyFilterTypeApi>

export const SpanPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: SpanPropertyFilterTypeApi,
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type SpanPropertyFilterApi = zod.input<typeof SpanPropertyFilterApi>
export type SpanPropertyFilterApiOutput = zod.output<typeof SpanPropertyFilterApi>

export const revenueAnalyticsPropertyFilterApiTypeDefault = `revenue_analytics`

export const RevenueAnalyticsPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('revenue_analytics').default(revenueAnalyticsPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type RevenueAnalyticsPropertyFilterApi = zod.input<typeof RevenueAnalyticsPropertyFilterApi>
export type RevenueAnalyticsPropertyFilterApiOutput = zod.output<typeof RevenueAnalyticsPropertyFilterApi>

export const accountCustomPropertyFilterApiTypeDefault = `account_custom_property`

export const AccountCustomPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod
        .literal('account_custom_property')
        .default(accountCustomPropertyFilterApiTypeDefault)
        .describe('Customer analytics account custom property — the key is the property definition id'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type AccountCustomPropertyFilterApi = zod.input<typeof AccountCustomPropertyFilterApi>
export type AccountCustomPropertyFilterApiOutput = zod.output<typeof AccountCustomPropertyFilterApi>

export const workflowVariablePropertyFilterApiTypeDefault = `workflow_variable`

export const WorkflowVariablePropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('workflow_variable').default(workflowVariablePropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type WorkflowVariablePropertyFilterApi = zod.input<typeof WorkflowVariablePropertyFilterApi>
export type WorkflowVariablePropertyFilterApiOutput = zod.output<typeof WorkflowVariablePropertyFilterApi>

export const calendarHeatmapFilterApiBucketBySessionStartDefault = false

export const CalendarHeatmapFilterApi = zod.object({
    bucketBySessionStart: zod
        .union([zod.boolean(), zod.null()])
        .default(calendarHeatmapFilterApiBucketBySessionStartDefault)
        .describe(
            "When true and the series math is `dau`\/`unique_users`, each user contributes to the (day-of-week, hour) bucket of their session's first event only — matching the web overview session-start attribution. When false (default), the user contributes to every bucket they have any event in. No effect on `total` math (event counts are unchanged either way)."
        ),
})

export type CalendarHeatmapFilterApi = zod.input<typeof CalendarHeatmapFilterApi>
export type CalendarHeatmapFilterApiOutput = zod.output<typeof CalendarHeatmapFilterApi>

export const compareFilterApiCompareDefault = false

export const CompareFilterApi = zod.object({
    compare: zod
        .union([zod.boolean(), zod.null()])
        .default(compareFilterApiCompareDefault)
        .describe('Whether to compare the current date range to a previous date range.'),
    compare_to: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe(
            'The date range to compare to. The value is a relative date. Examples of relative dates are: `-1y` for 1 year ago, `-14m` for 14 months ago, `-100w` for 100 weeks ago, `-14d` for 14 days ago, `-30h` for 30 hours ago.'
        ),
})

export type CompareFilterApi = zod.input<typeof CompareFilterApi>
export type CompareFilterApiOutput = zod.output<typeof CompareFilterApi>

export const ActionConversionGoalApi = zod.object({
    actionId: zod.number(),
})

export type ActionConversionGoalApi = zod.input<typeof ActionConversionGoalApi>
export type ActionConversionGoalApiOutput = zod.output<typeof ActionConversionGoalApi>

export const CustomEventConversionGoalApi = zod.object({
    customEventName: zod.string(),
})

export type CustomEventConversionGoalApi = zod.input<typeof CustomEventConversionGoalApi>
export type CustomEventConversionGoalApiOutput = zod.output<typeof CustomEventConversionGoalApi>

export const PropertyGroupFilterValueApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type PropertyGroupFilterValueApi = zod.input<typeof PropertyGroupFilterValueApi>
export type PropertyGroupFilterValueApiOutput = zod.output<typeof PropertyGroupFilterValueApi>

export const PropertyGroupFilterApi = zod.object({
    type: FilterLogicalOperatorApi,
    values: zod.array(PropertyGroupFilterValueApi),
})

export type PropertyGroupFilterApi = zod.input<typeof PropertyGroupFilterApi>
export type PropertyGroupFilterApiOutput = zod.output<typeof PropertyGroupFilterApi>

export const BoxPlotDatumApi = zod.object({
    day: zod.string(),
    label: zod.string(),
    max: zod.number(),
    mean: zod.number(),
    median: zod.number(),
    min: zod.number(),
    p25: zod.number(),
    p75: zod.number(),
    series_index: zod.union([zod.number(), zod.null()]).optional(),
    series_label: zod.union([zod.string(), zod.null()]).optional(),
})

export type BoxPlotDatumApi = zod.input<typeof BoxPlotDatumApi>
export type BoxPlotDatumApiOutput = zod.output<typeof BoxPlotDatumApi>

export const TrendsQueryResponseApi = zod.object({
    boxplot_data: zod.union([zod.array(BoxPlotDatumApi), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional().describe('Wether more breakdown values are available.'),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.record(zod.string(), zod.unknown())),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type TrendsQueryResponseApi = zod.input<typeof TrendsQueryResponseApi>
export type TrendsQueryResponseApiOutput = zod.output<typeof TrendsQueryResponseApi>

export const ActionsNodeApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ActionsNodeApi = zod.input<typeof ActionsNodeApi>
export type ActionsNodeApiOutput = zod.output<typeof ActionsNodeApi>

export const DataWarehouseNodeApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type DataWarehouseNodeApi = zod.input<typeof DataWarehouseNodeApi>
export type DataWarehouseNodeApiOutput = zod.output<typeof DataWarehouseNodeApi>

export const GroupNodeApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type GroupNodeApi = zod.input<typeof GroupNodeApi>
export type GroupNodeApiOutput = zod.output<typeof GroupNodeApi>

export const AggregationAxisFormatApi = zod.enum([
    'numeric',
    'duration',
    'duration_ms',
    'duration_ns',
    'percentage',
    'percentage_scaled',
    'currency',
    'short',
])

export type AggregationAxisFormatApi = zod.input<typeof AggregationAxisFormatApi>
export type AggregationAxisFormatApiOutput = zod.output<typeof AggregationAxisFormatApi>

export const DetailedResultsAggregationTypeApi = zod.enum(['total', 'average', 'median'])

export type DetailedResultsAggregationTypeApi = zod.input<typeof DetailedResultsAggregationTypeApi>
export type DetailedResultsAggregationTypeApiOutput = zod.output<typeof DetailedResultsAggregationTypeApi>

export const TrendsFormulaNodeApi = zod.object({
    custom_name: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe('Optional user-defined name for the formula'),
    formula: zod.string(),
})

export type TrendsFormulaNodeApi = zod.input<typeof TrendsFormulaNodeApi>
export type TrendsFormulaNodeApiOutput = zod.output<typeof TrendsFormulaNodeApi>

export const LegendPositionApi = zod.enum(['top', 'bottom', 'left', 'right'])

export type LegendPositionApi = zod.input<typeof LegendPositionApi>
export type LegendPositionApiOutput = zod.output<typeof LegendPositionApi>

export const MetricSummaryApi = zod.enum(['total', 'average', 'latest'])

export type MetricSummaryApi = zod.input<typeof MetricSummaryApi>
export type MetricSummaryApiOutput = zod.output<typeof MetricSummaryApi>

export const ResultCustomizationByApi = zod.enum(['value', 'position'])

export type ResultCustomizationByApi = zod.input<typeof ResultCustomizationByApi>
export type ResultCustomizationByApiOutput = zod.output<typeof ResultCustomizationByApi>

export const resultCustomizationByPositionApiAssignmentByDefault = `position`

export const ResultCustomizationByPositionApi = zod.object({
    assignmentBy: zod.literal('position').default(resultCustomizationByPositionApiAssignmentByDefault),
    color: zod.union([DataColorTokenApi, zod.null()]).optional(),
    hidden: zod.union([zod.boolean(), zod.null()]).optional(),
})

export type ResultCustomizationByPositionApi = zod.input<typeof ResultCustomizationByPositionApi>
export type ResultCustomizationByPositionApiOutput = zod.output<typeof ResultCustomizationByPositionApi>

export const YAxisScaleTypeApi = zod.enum(['log10', 'linear'])

export type YAxisScaleTypeApi = zod.input<typeof YAxisScaleTypeApi>
export type YAxisScaleTypeApiOutput = zod.output<typeof YAxisScaleTypeApi>

export const trendsFilterApiAggregationAxisFormatDefault = `numeric`
export const trendsFilterApiDisplayDefault = `ActionsLineGraph`
export const trendsFilterApiExcludeBoxPlotOutliersDefault = true
export const trendsFilterApiHideWeekendsDefault = false
export const trendsFilterApiLegendPositionDefault = `bottom`
export const trendsFilterApiMetricColorByDirectionDefault = false
export const trendsFilterApiMetricShowChangeDefault = true
export const trendsFilterApiMetricSummaryDefault = `total`
export const trendsFilterApiResultCustomizationByDefault = `value`
export const trendsFilterApiShowAlertThresholdLinesDefault = false
export const trendsFilterApiShowAnnotationsDefault = true
export const trendsFilterApiShowLegendDefault = false
export const trendsFilterApiShowMultipleYAxesDefault = false
export const trendsFilterApiShowPercentStackViewDefault = false
export const trendsFilterApiShowValuesOnSeriesDefault = false
export const trendsFilterApiSmoothingIntervalsDefault = 1
export const trendsFilterApiStackBreakdownValuesDefault = false
export const trendsFilterApiYAxisScaleTypeDefault = `linear`

export const TrendsFilterApi = zod.object({
    aggregationAxisFormat: zod
        .union([AggregationAxisFormatApi, zod.null()])
        .default(trendsFilterApiAggregationAxisFormatDefault)
        .describe(
            "Y-axis value formatter. Picks a human-friendly unit per value at render time without changing the underlying series values.\n\n- `numeric` (default): raw numbers, e.g. `1,234`.\n- `duration`: values are in seconds; rendered as friendly units per value (`45s`, `2m 12s`, `1h 4m`). Use this whenever the series is in seconds (latency, session length, time-to-event) instead of dividing in `formula` to force minutes or hours.\n- `duration_ms`: values are in milliseconds; rendered as friendly units (`850ms`, `1.5s`, `1m 4s`).\n- `percentage`: values are already in the 0-100 range; appends `%`.\n- `percentage_scaled`: values are a 0-1 ratio; multiplied and rendered as `%`.\n- `currency`: values are in the project's base currency (set in project settings, defaults to USD); rendered with that currency symbol. For values pinned to a specific currency regardless of project base (e.g. `$ai_total_cost_usd` is always USD), use `aggregationAxisPrefix` instead.\n- `short`: compact notation for large counts (`1.2K`, `3.4M`)."
        ),
    aggregationAxisPostfix: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe(
            'Literal suffix applied to every value (e.g. ` req`). Reserve for units that `aggregationAxisFormat` cannot express. Do not use ` mins`, ` s`, ` ms`, `%` etc. — pick the matching `aggregationAxisFormat` instead so the underlying values stay numerically correct for breakdowns, formulas, and alerts. Include any leading space yourself.'
        ),
    aggregationAxisPrefix: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe(
            "Literal prefix applied to every value (e.g. `$`). Use to pin a unit or currency symbol that does not depend on `aggregationAxisFormat` — for example, when values are denominated in a fixed currency regardless of the project's base currency. Include any trailing space yourself."
        ),
    breakdown_histogram_bin_count: zod.union([zod.number(), zod.null()]).optional(),
    chartStyle: zod
        .union([ChartStyleApi, zod.null()])
        .optional()
        .describe('Chart rendering style overrides (line shape).'),
    confidenceLevel: zod.union([zod.number(), zod.null()]).optional(),
    decimalPlaces: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Maximum number of decimal places shown. 1 or 2 is usually right for percentages and currency.'),
    detailedResultsAggregationType: zod
        .union([DetailedResultsAggregationTypeApi, zod.null()])
        .optional()
        .describe('detailed results table'),
    display: zod.union([ChartDisplayTypeApi, zod.null()]).default(trendsFilterApiDisplayDefault),
    excludeBoxPlotOutliers: zod
        .union([zod.boolean(), zod.null()])
        .default(trendsFilterApiExcludeBoxPlotOutliersDefault),
    formula: zod.union([zod.string(), zod.null()]).optional(),
    formulaNodes: zod
        .union([zod.array(TrendsFormulaNodeApi), zod.null()])
        .optional()
        .describe('List of formulas with optional custom names. Takes precedence over formula\/formulas if set.'),
    formulas: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    goalLines: zod
        .union([zod.array(GoalLineApi), zod.null()])
        .optional()
        .describe('Goal Lines'),
    hiddenLegendIndexes: zod.union([zod.array(zod.number()), zod.null()]).optional(),
    hideWeekends: zod.union([zod.boolean(), zod.null()]).default(trendsFilterApiHideWeekendsDefault),
    legendPosition: zod
        .union([LegendPositionApi, zod.null()])
        .default(trendsFilterApiLegendPositionDefault)
        .describe('Where the in-chart legend sits relative to the plot. Only applies to the in-chart legend.'),
    metricChangeDecreaseColor: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe('Metric display: change pill color when the metric decreased. Defaults to red.'),
    metricChangeIncreaseColor: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe('Metric display: change pill color when the metric increased. Defaults to green.'),
    metricColorByDirection: zod
        .union([zod.boolean(), zod.null()])
        .default(trendsFilterApiMetricColorByDirectionDefault)
        .describe('Metric display: color the sparkline by whether the metric increased or decreased.'),
    metricLineDecreaseColor: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe('Metric display: line color when the metric decreased. Defaults to red.'),
    metricLineIncreaseColor: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe('Metric display: line color when the metric increased. Defaults to green.'),
    metricShowChange: zod
        .union([zod.boolean(), zod.null()])
        .default(trendsFilterApiMetricShowChangeDefault)
        .describe('Show the period-over-period change pill on the Metric display.'),
    metricSummary: zod
        .union([MetricSummaryApi, zod.null()])
        .default(trendsFilterApiMetricSummaryDefault)
        .describe(
            'Metric display: which summary the resting headline shows — the period total, the average, or the latest point. Hovering the sparkline always shows the hovered point\'s value. Also drives the change pill: total\/average compare against the previous period when \"compare to previous\" is on; latest compares first→last of the series.'
        ),
    minDecimalPlaces: zod.union([zod.number(), zod.null()]).optional(),
    movingAverageIntervals: zod.union([zod.number(), zod.null()]).optional(),
    resultCustomizationBy: zod
        .union([ResultCustomizationByApi, zod.null()])
        .default(trendsFilterApiResultCustomizationByDefault)
        .describe('Wether result datasets are associated by their values or by their order.'),
    resultCustomizations: zod
        .union([
            zod.record(zod.string(), ResultCustomizationByValueApi),
            zod.record(zod.string(), ResultCustomizationByPositionApi),
            zod.null(),
        ])
        .optional()
        .describe('Customizations for the appearance of result datasets.'),
    showAlertThresholdLines: zod
        .union([zod.boolean(), zod.null()])
        .default(trendsFilterApiShowAlertThresholdLinesDefault),
    showAnnotations: zod.union([zod.boolean(), zod.null()]).default(trendsFilterApiShowAnnotationsDefault),
    showConfidenceIntervals: zod.union([zod.boolean(), zod.null()]).optional(),
    showLabelsOnSeries: zod.union([zod.boolean(), zod.null()]).optional(),
    showLegend: zod.union([zod.boolean(), zod.null()]).default(trendsFilterApiShowLegendDefault),
    showMovingAverage: zod.union([zod.boolean(), zod.null()]).optional(),
    showMultipleYAxes: zod.union([zod.boolean(), zod.null()]).default(trendsFilterApiShowMultipleYAxesDefault),
    showPercentStackView: zod.union([zod.boolean(), zod.null()]).default(trendsFilterApiShowPercentStackViewDefault),
    showTrendLines: zod.union([zod.boolean(), zod.null()]).optional(),
    showValuesOnSeries: zod.union([zod.boolean(), zod.null()]).default(trendsFilterApiShowValuesOnSeriesDefault),
    smoothingIntervals: zod.union([zod.number(), zod.null()]).default(trendsFilterApiSmoothingIntervalsDefault),
    stackBreakdownValues: zod
        .union([zod.boolean(), zod.null()])
        .default(trendsFilterApiStackBreakdownValuesDefault)
        .describe(
            "On the horizontal bar-value chart, stack a series' breakdown values into a single bar instead of rendering one bar per breakdown value."
        ),
    xAxisLabel: zod.union([zod.string(), zod.null()]).optional().describe('Custom label rendered under the X axis.'),
    yAxisLabel: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe('Custom label rendered alongside the Y axis.'),
    yAxisScaleType: zod.union([YAxisScaleTypeApi, zod.null()]).default(trendsFilterApiYAxisScaleTypeDefault),
})

export type TrendsFilterApi = zod.input<typeof TrendsFilterApi>
export type TrendsFilterApiOutput = zod.output<typeof TrendsFilterApi>

export const FunnelsFilterApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type FunnelsFilterApi = zod.input<typeof FunnelsFilterApi>
export type FunnelsFilterApiOutput = zod.output<typeof FunnelsFilterApi>

export const FunnelsQueryResponseApi = zod.object({
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.unknown(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    total_median_conversion_time: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe(
            'Median total conversion time across all completers, computed breakdown-agnostically for the Steps viz header.'
        ),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type FunnelsQueryResponseApi = zod.input<typeof FunnelsQueryResponseApi>
export type FunnelsQueryResponseApiOutput = zod.output<typeof FunnelsQueryResponseApi>

export const FunnelsDataWarehouseNodeApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type FunnelsDataWarehouseNodeApi = zod.input<typeof FunnelsDataWarehouseNodeApi>
export type FunnelsDataWarehouseNodeApiOutput = zod.output<typeof FunnelsDataWarehouseNodeApi>

export const RetentionValueApi = zod.object({
    aggregation_value: zod.union([zod.number(), zod.null()]).optional(),
    count: zod.number(),
    label: zod.union([zod.string(), zod.null()]).optional(),
})

export type RetentionValueApi = zod.input<typeof RetentionValueApi>
export type RetentionValueApiOutput = zod.output<typeof RetentionValueApi>

export const RetentionResultApi = zod.object({
    breakdown_value: zod
        .union([zod.string(), zod.number(), zod.null()])
        .optional()
        .describe('Optional breakdown value for retention cohorts'),
    date: zod.iso.datetime({ offset: true }),
    label: zod.string(),
    values: zod.array(RetentionValueApi),
})

export type RetentionResultApi = zod.input<typeof RetentionResultApi>
export type RetentionResultApiOutput = zod.output<typeof RetentionResultApi>

export const RetentionQueryResponseApi = zod.object({
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(RetentionResultApi),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type RetentionQueryResponseApi = zod.input<typeof RetentionQueryResponseApi>
export type RetentionQueryResponseApiOutput = zod.output<typeof RetentionQueryResponseApi>

export const RetentionFilterApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type RetentionFilterApi = zod.input<typeof RetentionFilterApi>
export type RetentionFilterApiOutput = zod.output<typeof RetentionFilterApi>

export const FunnelPathsFilterApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type FunnelPathsFilterApi = zod.input<typeof FunnelPathsFilterApi>
export type FunnelPathsFilterApiOutput = zod.output<typeof FunnelPathsFilterApi>

export const PathTypeApi = zod.enum(['$pageview', '$screen', 'custom_event', 'hogql'])

export type PathTypeApi = zod.input<typeof PathTypeApi>
export type PathTypeApiOutput = zod.output<typeof PathTypeApi>

export const PathCleaningFilterApi = zod.object({
    alias: zod.union([zod.string(), zod.null()]).optional(),
    order: zod.union([zod.number(), zod.null()]).optional(),
    regex: zod.union([zod.string(), zod.null()]).optional(),
})

export type PathCleaningFilterApi = zod.input<typeof PathCleaningFilterApi>
export type PathCleaningFilterApiOutput = zod.output<typeof PathCleaningFilterApi>

export const pathsFilterApiEdgeLimitDefault = 50
export const pathsFilterApiStepLimitDefault = 5

export const PathsFilterApi = zod.object({
    edgeLimit: zod.union([zod.number(), zod.null()]).default(pathsFilterApiEdgeLimitDefault),
    endPoint: zod.union([zod.string(), zod.null()]).optional(),
    excludeEvents: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    includeEventTypes: zod.union([zod.array(PathTypeApi), zod.null()]).optional(),
    localPathCleaningFilters: zod.union([zod.array(PathCleaningFilterApi), zod.null()]).optional(),
    maxEdgeWeight: zod.union([zod.number(), zod.null()]).optional(),
    minEdgeWeight: zod.union([zod.number(), zod.null()]).optional(),
    pathDropoffKey: zod.union([zod.string(), zod.null()]).optional().describe('Relevant only within actors query'),
    pathEndKey: zod.union([zod.string(), zod.null()]).optional().describe('Relevant only within actors query'),
    pathGroupings: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    pathReplacements: zod.union([zod.boolean(), zod.null()]).optional(),
    pathStartKey: zod.union([zod.string(), zod.null()]).optional().describe('Relevant only within actors query'),
    pathsHogQLExpression: zod.union([zod.string(), zod.null()]).optional(),
    showFullUrls: zod.union([zod.boolean(), zod.null()]).optional(),
    startPoint: zod.union([zod.string(), zod.null()]).optional(),
    stepLimit: zod.union([zod.number(), zod.null()]).default(pathsFilterApiStepLimitDefault),
})

export type PathsFilterApi = zod.input<typeof PathsFilterApi>
export type PathsFilterApiOutput = zod.output<typeof PathsFilterApi>

export const PathsLinkApi = zod.object({
    average_conversion_time: zod.number(),
    source: zod.string(),
    target: zod.string(),
    value: zod.number(),
})

export type PathsLinkApi = zod.input<typeof PathsLinkApi>
export type PathsLinkApiOutput = zod.output<typeof PathsLinkApi>

export const PathsQueryResponseApi = zod.object({
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(PathsLinkApi),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type PathsQueryResponseApi = zod.input<typeof PathsQueryResponseApi>
export type PathsQueryResponseApiOutput = zod.output<typeof PathsQueryResponseApi>

export const StickinessQueryResponseApi = zod.object({
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.record(zod.string(), zod.unknown())),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type StickinessQueryResponseApi = zod.input<typeof StickinessQueryResponseApi>
export type StickinessQueryResponseApiOutput = zod.output<typeof StickinessQueryResponseApi>

export const StickinessComputationModeApi = zod.enum(['non_cumulative', 'cumulative'])

export type StickinessComputationModeApi = zod.input<typeof StickinessComputationModeApi>
export type StickinessComputationModeApiOutput = zod.output<typeof StickinessComputationModeApi>

export const StickinessOperatorApi = zod.enum(['gte', 'lte', 'exact'])

export type StickinessOperatorApi = zod.input<typeof StickinessOperatorApi>
export type StickinessOperatorApiOutput = zod.output<typeof StickinessOperatorApi>

export const StickinessCriteriaApi = zod.object({
    operator: StickinessOperatorApi,
    value: zod.number().min(1),
})

export type StickinessCriteriaApi = zod.input<typeof StickinessCriteriaApi>
export type StickinessCriteriaApiOutput = zod.output<typeof StickinessCriteriaApi>

export const stickinessFilterApiLegendPositionDefault = `bottom`
export const stickinessFilterApiResultCustomizationByDefault = `value`

export const StickinessFilterApi = zod.object({
    chartStyle: zod
        .union([ChartStyleApi, zod.null()])
        .optional()
        .describe('Chart rendering style overrides (line shape).'),
    computedAs: zod.union([StickinessComputationModeApi, zod.null()]).optional(),
    display: zod.union([ChartDisplayTypeApi, zod.null()]).optional(),
    hiddenLegendIndexes: zod.union([zod.array(zod.number()), zod.null()]).optional(),
    legendPosition: zod
        .union([LegendPositionApi, zod.null()])
        .default(stickinessFilterApiLegendPositionDefault)
        .describe('Where the in-chart legend sits relative to the plot. Only applies to the in-chart legend.'),
    resultCustomizationBy: zod
        .union([ResultCustomizationByApi, zod.null()])
        .default(stickinessFilterApiResultCustomizationByDefault)
        .describe('Whether result datasets are associated by their values or by their order.'),
    resultCustomizations: zod
        .union([
            zod.record(zod.string(), ResultCustomizationByValueApi),
            zod.record(zod.string(), ResultCustomizationByPositionApi),
            zod.null(),
        ])
        .optional()
        .describe('Customizations for the appearance of result datasets.'),
    showLegend: zod.union([zod.boolean(), zod.null()]).optional(),
    showMultipleYAxes: zod.union([zod.boolean(), zod.null()]).optional(),
    showValuesOnSeries: zod.union([zod.boolean(), zod.null()]).optional(),
    stickinessCriteria: zod.union([StickinessCriteriaApi, zod.null()]).optional(),
})

export type StickinessFilterApi = zod.input<typeof StickinessFilterApi>
export type StickinessFilterApiOutput = zod.output<typeof StickinessFilterApi>

export const LifecycleToggleApi = zod.enum(['new', 'resurrecting', 'returning', 'dormant'])

export type LifecycleToggleApi = zod.input<typeof LifecycleToggleApi>
export type LifecycleToggleApiOutput = zod.output<typeof LifecycleToggleApi>

export const lifecycleFilterApiLegendPositionDefault = `bottom`
export const lifecycleFilterApiShowLegendDefault = false
export const lifecycleFilterApiStackedDefault = true

export const LifecycleFilterApi = zod.object({
    legendPosition: zod
        .union([LegendPositionApi, zod.null()])
        .default(lifecycleFilterApiLegendPositionDefault)
        .describe('Where the in-chart legend sits relative to the plot. Only applies to the in-chart legend.'),
    showLegend: zod.union([zod.boolean(), zod.null()]).default(lifecycleFilterApiShowLegendDefault),
    showPercentagesOnSeries: zod
        .union([zod.boolean(), zod.null()])
        .optional()
        .describe(
            'Append per-band percentage to each value label (e.g. `580 (42%)`). Requires `showValuesOnSeries` — on its own it has no visible effect.'
        ),
    showValuesOnSeries: zod.union([zod.boolean(), zod.null()]).optional(),
    stacked: zod.union([zod.boolean(), zod.null()]).default(lifecycleFilterApiStackedDefault),
    toggledLifecycles: zod.union([zod.array(LifecycleToggleApi), zod.null()]).optional(),
})

export type LifecycleFilterApi = zod.input<typeof LifecycleFilterApi>
export type LifecycleFilterApiOutput = zod.output<typeof LifecycleFilterApi>

export const LifecycleQueryResponseApi = zod.object({
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.record(zod.string(), zod.unknown())),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type LifecycleQueryResponseApi = zod.input<typeof LifecycleQueryResponseApi>
export type LifecycleQueryResponseApiOutput = zod.output<typeof LifecycleQueryResponseApi>

export const LifecycleDataWarehouseNodeApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type LifecycleDataWarehouseNodeApi = zod.input<typeof LifecycleDataWarehouseNodeApi>
export type LifecycleDataWarehouseNodeApiOutput = zod.output<typeof LifecycleDataWarehouseNodeApi>

export const WebStatsBreakdownApi = zod.enum([
    'Page',
    'InitialPage',
    'ExitPage',
    'ExitClick',
    'PreviousPage',
    'ScreenName',
    'InitialChannelType',
    'InitialReferringDomain',
    'InitialReferringURL',
    'InitialUTMSource',
    'InitialUTMCampaign',
    'InitialUTMMedium',
    'InitialUTMTerm',
    'InitialUTMContent',
    'InitialUTMSourceMediumCampaign',
    'FirstPageviewChannelType',
    'FirstPageviewReferringDomain',
    'FirstPageviewUTMSource',
    'FirstPageviewUTMCampaign',
    'FirstPageviewUTMMedium',
    'FirstPageviewUTMTerm',
    'FirstPageviewUTMContent',
    'FirstPageviewUTMSourceMediumCampaign',
    'Browser',
    'OS',
    'Viewport',
    'DeviceType',
    'Country',
    'Region',
    'City',
    'Timezone',
    'Language',
    'FrustrationMetrics',
])

export type WebStatsBreakdownApi = zod.input<typeof WebStatsBreakdownApi>
export type WebStatsBreakdownApiOutput = zod.output<typeof WebStatsBreakdownApi>

export const WebAnalyticsOrderByFieldsApi = zod.enum([
    'Visitors',
    'Views',
    'AvgTimeOnPage',
    'Clicks',
    'BounceRate',
    'AverageScrollPercentage',
    'ScrollGt80Percentage',
    'TotalConversions',
    'UniqueConversions',
    'ConversionRate',
    'ConvertingUsers',
    'RageClicks',
    'DeadClicks',
    'Errors',
])

export type WebAnalyticsOrderByFieldsApi = zod.input<typeof WebAnalyticsOrderByFieldsApi>
export type WebAnalyticsOrderByFieldsApiOutput = zod.output<typeof WebAnalyticsOrderByFieldsApi>

export const WebAnalyticsOrderByDirectionApi = zod.enum(['ASC', 'DESC'])

export type WebAnalyticsOrderByDirectionApi = zod.input<typeof WebAnalyticsOrderByDirectionApi>
export type WebAnalyticsOrderByDirectionApiOutput = zod.output<typeof WebAnalyticsOrderByDirectionApi>

export const WebStatsTableQueryResponseApi = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    preComputeStale: zod
        .union([zod.boolean(), zod.null()])
        .optional()
        .describe(
            'Whether a lazy-precompute read was served from expired-within-grace (stale) jobs instead of recomputing inline.'
        ),
    preComputeStrategy: zod.union([WebAnalyticsPreComputeStrategyApi, zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.unknown()),
    samplingRate: zod.union([SamplingRateApi, zod.null()]).optional(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type WebStatsTableQueryResponseApi = zod.input<typeof WebStatsTableQueryResponseApi>
export type WebStatsTableQueryResponseApiOutput = zod.output<typeof WebStatsTableQueryResponseApi>

export const WebAnalyticsSamplingApi = zod.object({
    enabled: zod.union([zod.boolean(), zod.null()]).optional(),
    forceSamplingRate: zod.union([SamplingRateApi, zod.null()]).optional(),
})

export type WebAnalyticsSamplingApi = zod.input<typeof WebAnalyticsSamplingApi>
export type WebAnalyticsSamplingApiOutput = zod.output<typeof WebAnalyticsSamplingApi>

export const WebOverviewQueryResponseApi = zod.object({
    dateFrom: zod.union([zod.string(), zod.null()]).optional(),
    dateTo: zod.union([zod.string(), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    preComputeStrategy: zod.union([WebAnalyticsPreComputeStrategyApi, zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(WebOverviewItemApi),
    samplingRate: zod.union([SamplingRateApi, zod.null()]).optional(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type WebOverviewQueryResponseApi = zod.input<typeof WebOverviewQueryResponseApi>
export type WebOverviewQueryResponseApiOutput = zod.output<typeof WebOverviewQueryResponseApi>

export const ExperimentSignificanceCodeApi = zod.enum([
    'significant',
    'not_enough_exposure',
    'low_win_probability',
    'high_loss',
    'high_p_value',
])

export type ExperimentSignificanceCodeApi = zod.input<typeof ExperimentSignificanceCodeApi>
export type ExperimentSignificanceCodeApiOutput = zod.output<typeof ExperimentSignificanceCodeApi>

export const ExperimentVariantFunnelsBaseStatsApi = zod.object({
    failure_count: zod.number(),
    key: zod.string(),
    success_count: zod.number(),
})

export type ExperimentVariantFunnelsBaseStatsApi = zod.input<typeof ExperimentVariantFunnelsBaseStatsApi>
export type ExperimentVariantFunnelsBaseStatsApiOutput = zod.output<typeof ExperimentVariantFunnelsBaseStatsApi>

export const ExperimentVariantTrendsBaseStatsApi = zod.object({
    absolute_exposure: zod.number(),
    count: zod.number(),
    exposure: zod.number(),
    key: zod.string(),
})

export type ExperimentVariantTrendsBaseStatsApi = zod.input<typeof ExperimentVariantTrendsBaseStatsApi>
export type ExperimentVariantTrendsBaseStatsApiOutput = zod.output<typeof ExperimentVariantTrendsBaseStatsApi>

export const BaseMathTypeApi = zod.enum([
    'total',
    'dau',
    'weekly_active',
    'monthly_active',
    'unique_session',
    'first_time_for_user',
    'first_matching_event_for_user',
])

export type BaseMathTypeApi = zod.input<typeof BaseMathTypeApi>
export type BaseMathTypeApiOutput = zod.output<typeof BaseMathTypeApi>

export const FunnelMathTypeApi = zod.enum(['total', 'first_time_for_user', 'first_time_for_user_with_filters'])

export type FunnelMathTypeApi = zod.input<typeof FunnelMathTypeApi>
export type FunnelMathTypeApiOutput = zod.output<typeof FunnelMathTypeApi>

export const PropertyMathTypeApi = zod.enum(['avg', 'sum', 'min', 'max', 'median', 'p75', 'p90', 'p95', 'p99'])

export type PropertyMathTypeApi = zod.input<typeof PropertyMathTypeApi>
export type PropertyMathTypeApiOutput = zod.output<typeof PropertyMathTypeApi>

export const CountPerActorMathTypeApi = zod.enum([
    'avg_count_per_actor',
    'min_count_per_actor',
    'max_count_per_actor',
    'median_count_per_actor',
    'p75_count_per_actor',
    'p90_count_per_actor',
    'p95_count_per_actor',
    'p99_count_per_actor',
])

export type CountPerActorMathTypeApi = zod.input<typeof CountPerActorMathTypeApi>
export type CountPerActorMathTypeApiOutput = zod.output<typeof CountPerActorMathTypeApi>

export const ExperimentMetricMathTypeApi = zod.enum([
    'total',
    'sum',
    'unique_session',
    'min',
    'max',
    'avg',
    'dau',
    'unique_group',
    'hogql',
])

export type ExperimentMetricMathTypeApi = zod.input<typeof ExperimentMetricMathTypeApi>
export type ExperimentMetricMathTypeApiOutput = zod.output<typeof ExperimentMetricMathTypeApi>

export const CalendarHeatmapMathTypeApi = zod.enum(['total', 'dau'])

export type CalendarHeatmapMathTypeApi = zod.input<typeof CalendarHeatmapMathTypeApi>
export type CalendarHeatmapMathTypeApiOutput = zod.output<typeof CalendarHeatmapMathTypeApi>

export const MathGroupTypeIndexApi = zod.union([
    zod.literal(0),
    zod.literal(1),
    zod.literal(2),
    zod.literal(3),
    zod.literal(4),
])

export type MathGroupTypeIndexApi = zod.input<typeof MathGroupTypeIndexApi>
export type MathGroupTypeIndexApiOutput = zod.output<typeof MathGroupTypeIndexApi>

export const CurrencyCodeApi = zod.enum([
    'AED',
    'AFN',
    'ALL',
    'AMD',
    'ANG',
    'AOA',
    'ARS',
    'AUD',
    'AWG',
    'AZN',
    'BAM',
    'BBD',
    'BDT',
    'BGN',
    'BHD',
    'BIF',
    'BMD',
    'BND',
    'BOB',
    'BRL',
    'BSD',
    'BTC',
    'BTN',
    'BWP',
    'BYN',
    'BZD',
    'CAD',
    'CDF',
    'CHF',
    'CLP',
    'CNY',
    'COP',
    'CRC',
    'CVE',
    'CZK',
    'DJF',
    'DKK',
    'DOP',
    'DZD',
    'EGP',
    'ERN',
    'ETB',
    'EUR',
    'FJD',
    'GBP',
    'GEL',
    'GHS',
    'GIP',
    'GMD',
    'GNF',
    'GTQ',
    'GYD',
    'HKD',
    'HNL',
    'HRK',
    'HTG',
    'HUF',
    'IDR',
    'ILS',
    'INR',
    'IQD',
    'IRR',
    'ISK',
    'JMD',
    'JOD',
    'JPY',
    'KES',
    'KGS',
    'KHR',
    'KMF',
    'KRW',
    'KWD',
    'KYD',
    'KZT',
    'LAK',
    'LBP',
    'LKR',
    'LRD',
    'LTL',
    'LVL',
    'LSL',
    'LYD',
    'MAD',
    'MDL',
    'MGA',
    'MKD',
    'MMK',
    'MNT',
    'MOP',
    'MRU',
    'MTL',
    'MUR',
    'MVR',
    'MWK',
    'MXN',
    'MYR',
    'MZN',
    'NAD',
    'NGN',
    'NIO',
    'NOK',
    'NPR',
    'NZD',
    'OMR',
    'PAB',
    'PEN',
    'PGK',
    'PHP',
    'PKR',
    'PLN',
    'PYG',
    'QAR',
    'RON',
    'RSD',
    'RUB',
    'RWF',
    'SAR',
    'SBD',
    'SCR',
    'SDG',
    'SEK',
    'SGD',
    'SRD',
    'SSP',
    'STN',
    'SYP',
    'SZL',
    'THB',
    'TJS',
    'TMT',
    'TND',
    'TOP',
    'TRY',
    'TTD',
    'TWD',
    'TZS',
    'UAH',
    'UGX',
    'USD',
    'UYU',
    'UZS',
    'VES',
    'VND',
    'VUV',
    'WST',
    'XAF',
    'XCD',
    'XOF',
    'XPF',
    'YER',
    'ZAR',
    'ZMW',
])

export type CurrencyCodeApi = zod.input<typeof CurrencyCodeApi>
export type CurrencyCodeApiOutput = zod.output<typeof CurrencyCodeApi>

export const RevenueCurrencyPropertyConfigApi = zod.object({
    property: zod.union([zod.string(), zod.null()]).optional(),
    static: zod.union([CurrencyCodeApi, zod.null()]).optional(),
})

export type RevenueCurrencyPropertyConfigApi = zod.input<typeof RevenueCurrencyPropertyConfigApi>
export type RevenueCurrencyPropertyConfigApiOutput = zod.output<typeof RevenueCurrencyPropertyConfigApi>

export const EventsQueryActionStepApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type EventsQueryActionStepApi = zod.input<typeof EventsQueryActionStepApi>
export type EventsQueryActionStepApiOutput = zod.output<typeof EventsQueryActionStepApi>

export const EventsQueryResponseApi = zod.object({
    columns: zod.array(zod.unknown()),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.string().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    nextCursor: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe('Cursor for fetching the next page of results'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.array(zod.unknown())),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.array(zod.string()),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type EventsQueryResponseApi = zod.input<typeof EventsQueryResponseApi>
export type EventsQueryResponseApiOutput = zod.output<typeof EventsQueryResponseApi>

export const InsightActorsQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type InsightActorsQueryApi = zod.input<typeof InsightActorsQueryApi>
export type InsightActorsQueryApiOutput = zod.output<typeof InsightActorsQueryApi>

export const ActorsQueryResponseApi = zod.object({
    columns: zod.array(zod.unknown()),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.string().describe('Generated HogQL query.'),
    limit: zod.number(),
    missing_actors_count: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.number(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.array(zod.unknown())),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type ActorsQueryResponseApi = zod.input<typeof ActorsQueryResponseApi>
export type ActorsQueryResponseApiOutput = zod.output<typeof ActorsQueryResponseApi>

export const FunnelsActorsQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type FunnelsActorsQueryApi = zod.input<typeof FunnelsActorsQueryApi>
export type FunnelsActorsQueryApiOutput = zod.output<typeof FunnelsActorsQueryApi>

export const FunnelCorrelationActorsQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type FunnelCorrelationActorsQueryApi = zod.input<typeof FunnelCorrelationActorsQueryApi>
export type FunnelCorrelationActorsQueryApiOutput = zod.output<typeof FunnelCorrelationActorsQueryApi>

export const ExperimentActorsQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentActorsQueryApi = zod.input<typeof ExperimentActorsQueryApi>
export type ExperimentActorsQueryApiOutput = zod.output<typeof ExperimentActorsQueryApi>

export const StickinessActorsQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type StickinessActorsQueryApi = zod.input<typeof StickinessActorsQueryApi>
export type StickinessActorsQueryApiOutput = zod.output<typeof StickinessActorsQueryApi>

export const HogQLFiltersApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type HogQLFiltersApi = zod.input<typeof HogQLFiltersApi>
export type HogQLFiltersApiOutput = zod.output<typeof HogQLFiltersApi>

export const HogQLQueryResponseApi = zod.object({
    clickhouse: zod.union([zod.string(), zod.null()]).optional().describe('Executed ClickHouse query'),
    columns: zod
        .union([zod.array(zod.unknown()), zod.null()])
        .optional()
        .describe('Returned columns'),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    explain: zod
        .union([zod.array(zod.string()), zod.null()])
        .optional()
        .describe('Query explanation output'),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    metadata: zod.union([HogQLMetadataResponseApi, zod.null()]).optional().describe('Query metadata output'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query: zod.union([zod.string(), zod.null()]).optional().describe('Input query string'),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.unknown()),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod
        .union([zod.array(zod.unknown()), zod.null()])
        .optional()
        .describe('Types of returned columns'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type HogQLQueryResponseApi = zod.input<typeof HogQLQueryResponseApi>
export type HogQLQueryResponseApiOutput = zod.output<typeof HogQLQueryResponseApi>

export const HogQLVariableApi = zod.object({
    code_name: zod.string(),
    isNull: zod.union([zod.boolean(), zod.null()]).optional(),
    value: zod.unknown().optional(),
    variableId: zod.string(),
})

export type HogQLVariableApi = zod.input<typeof HogQLVariableApi>
export type HogQLVariableApiOutput = zod.output<typeof HogQLVariableApi>

export const WebExternalClicksTableQueryResponseApi = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.unknown()),
    samplingRate: zod.union([SamplingRateApi, zod.null()]).optional(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type WebExternalClicksTableQueryResponseApi = zod.input<typeof WebExternalClicksTableQueryResponseApi>
export type WebExternalClicksTableQueryResponseApiOutput = zod.output<typeof WebExternalClicksTableQueryResponseApi>

export const WebBotsBreakdownApi = zod.enum(['Crawler', 'Path'])

export type WebBotsBreakdownApi = zod.input<typeof WebBotsBreakdownApi>
export type WebBotsBreakdownApiOutput = zod.output<typeof WebBotsBreakdownApi>

export const WebBotsTableQueryResponseApi = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.unknown()),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type WebBotsTableQueryResponseApi = zod.input<typeof WebBotsTableQueryResponseApi>
export type WebBotsTableQueryResponseApiOutput = zod.output<typeof WebBotsTableQueryResponseApi>

export const WebGoalsQueryResponseApi = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    preComputeStrategy: zod.union([WebAnalyticsPreComputeStrategyApi, zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.unknown()),
    samplingRate: zod.union([SamplingRateApi, zod.null()]).optional(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type WebGoalsQueryResponseApi = zod.input<typeof WebGoalsQueryResponseApi>
export type WebGoalsQueryResponseApiOutput = zod.output<typeof WebGoalsQueryResponseApi>

export const WebVitalsMetricApi = zod.enum(['INP', 'LCP', 'CLS', 'FCP'])

export type WebVitalsMetricApi = zod.input<typeof WebVitalsMetricApi>
export type WebVitalsMetricApiOutput = zod.output<typeof WebVitalsMetricApi>

export const WebVitalsPercentileApi = zod.enum(['p75', 'p90', 'p99'])

export type WebVitalsPercentileApi = zod.input<typeof WebVitalsPercentileApi>
export type WebVitalsPercentileApiOutput = zod.output<typeof WebVitalsPercentileApi>

export const webVitalsPathBreakdownQueryResponseApiResultsMax = 1

export const WebVitalsPathBreakdownQueryResponseApi = zod.object({
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    preComputeStrategy: zod.union([WebAnalyticsPreComputeStrategyApi, zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(WebVitalsPathBreakdownResultApi).min(1).max(webVitalsPathBreakdownQueryResponseApiResultsMax),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type WebVitalsPathBreakdownQueryResponseApi = zod.input<typeof WebVitalsPathBreakdownQueryResponseApi>
export type WebVitalsPathBreakdownQueryResponseApiOutput = zod.output<typeof WebVitalsPathBreakdownQueryResponseApi>

export const SessionsQueryResponseApi = zod.object({
    columns: zod.array(zod.unknown()),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.string().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.array(zod.unknown())),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.array(zod.string()),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type SessionsQueryResponseApi = zod.input<typeof SessionsQueryResponseApi>
export type SessionsQueryResponseApiOutput = zod.output<typeof SessionsQueryResponseApi>

export const ConversionGoalFilter1Api = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ConversionGoalFilter1Api = zod.input<typeof ConversionGoalFilter1Api>
export type ConversionGoalFilter1ApiOutput = zod.output<typeof ConversionGoalFilter1Api>

export const ConversionGoalFilter2Api = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ConversionGoalFilter2Api = zod.input<typeof ConversionGoalFilter2Api>
export type ConversionGoalFilter2ApiOutput = zod.output<typeof ConversionGoalFilter2Api>

export const ConversionGoalFilter3Api = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ConversionGoalFilter3Api = zod.input<typeof ConversionGoalFilter3Api>
export type ConversionGoalFilter3ApiOutput = zod.output<typeof ConversionGoalFilter3Api>

export const MarketingAnalyticsDrillDownLevelApi = zod.enum([
    'channel',
    'channel_source',
    'source',
    'campaign',
    'ad_group',
    'ad',
    'medium',
    'content',
    'term',
])

export type MarketingAnalyticsDrillDownLevelApi = zod.input<typeof MarketingAnalyticsDrillDownLevelApi>
export type MarketingAnalyticsDrillDownLevelApiOutput = zod.output<typeof MarketingAnalyticsDrillDownLevelApi>

export const IntegrationFilterApi = zod.object({
    integrationSourceIds: zod
        .union([zod.array(zod.string()), zod.null()])
        .optional()
        .describe('Selected integration source IDs to filter by (e.g., table IDs or source map IDs)'),
})

export type IntegrationFilterApi = zod.input<typeof IntegrationFilterApi>
export type IntegrationFilterApiOutput = zod.output<typeof IntegrationFilterApi>

export const MarketingAnalyticsOrderByEnumApi = zod.enum(['ASC', 'DESC'])

export type MarketingAnalyticsOrderByEnumApi = zod.input<typeof MarketingAnalyticsOrderByEnumApi>
export type MarketingAnalyticsOrderByEnumApiOutput = zod.output<typeof MarketingAnalyticsOrderByEnumApi>

export const MarketingAnalyticsTableQueryResponseApi = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.array(MarketingAnalyticsItemApi)),
    samplingRate: zod.union([SamplingRateApi, zod.null()]).optional(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type MarketingAnalyticsTableQueryResponseApi = zod.input<typeof MarketingAnalyticsTableQueryResponseApi>
export type MarketingAnalyticsTableQueryResponseApiOutput = zod.output<typeof MarketingAnalyticsTableQueryResponseApi>

export const MarketingAnalyticsAggregatedQueryResponseApi = zod.object({
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.record(zod.string(), MarketingAnalyticsItemApi),
    samplingRate: zod.union([SamplingRateApi, zod.null()]).optional(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type MarketingAnalyticsAggregatedQueryResponseApi = zod.input<
    typeof MarketingAnalyticsAggregatedQueryResponseApi
>
export type MarketingAnalyticsAggregatedQueryResponseApiOutput = zod.output<
    typeof MarketingAnalyticsAggregatedQueryResponseApi
>

export const NonIntegratedConversionsTableQueryResponseApi = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(zod.array(MarketingAnalyticsItemApi)),
    samplingRate: zod.union([SamplingRateApi, zod.null()]).optional(),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type NonIntegratedConversionsTableQueryResponseApi = zod.input<
    typeof NonIntegratedConversionsTableQueryResponseApi
>
export type NonIntegratedConversionsTableQueryResponseApiOutput = zod.output<
    typeof NonIntegratedConversionsTableQueryResponseApi
>

export const ErrorTrackingOrderByApi = zod.enum(['last_seen', 'first_seen', 'occurrences', 'users', 'sessions'])

export type ErrorTrackingOrderByApi = zod.input<typeof ErrorTrackingOrderByApi>
export type ErrorTrackingOrderByApiOutput = zod.output<typeof ErrorTrackingOrderByApi>

export const OrderDirection2Api = zod.enum(['ASC', 'DESC'])

export type OrderDirection2Api = zod.input<typeof OrderDirection2Api>
export type OrderDirection2ApiOutput = zod.output<typeof OrderDirection2Api>

export const ErrorTrackingPendingFingerprintIssueStateUpdateApi = zod.object({
    assigned_role_id: zod.union([zod.string(), zod.null()]).optional(),
    assigned_user_id: zod.union([zod.number(), zod.null()]).optional(),
    fingerprint: zod.string(),
    first_seen: zod.string().describe('ISO 8601 datetime string.'),
    is_deleted: zod.number(),
    issue_description: zod.union([zod.string(), zod.null()]).optional(),
    issue_id: zod.string(),
    issue_name: zod.union([zod.string(), zod.null()]).optional(),
    issue_status: zod.string(),
    version: zod.number().describe('Client-stamped monotonic version (`Date.now()` ms at mutation success).'),
})

export type ErrorTrackingPendingFingerprintIssueStateUpdateApi = zod.input<
    typeof ErrorTrackingPendingFingerprintIssueStateUpdateApi
>
export type ErrorTrackingPendingFingerprintIssueStateUpdateApiOutput = zod.output<
    typeof ErrorTrackingPendingFingerprintIssueStateUpdateApi
>

export const ErrorTrackingQueryResponseApi = zod.object({
    columns: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(ErrorTrackingIssueApi),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type ErrorTrackingQueryResponseApi = zod.input<typeof ErrorTrackingQueryResponseApi>
export type ErrorTrackingQueryResponseApiOutput = zod.output<typeof ErrorTrackingQueryResponseApi>

export const ExperimentFunnelsQueryResponseApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentFunnelsQueryResponseApi = zod.input<typeof ExperimentFunnelsQueryResponseApi>
export type ExperimentFunnelsQueryResponseApiOutput = zod.output<typeof ExperimentFunnelsQueryResponseApi>

export const ExperimentTrendsQueryResponseApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentTrendsQueryResponseApi = zod.input<typeof ExperimentTrendsQueryResponseApi>
export type ExperimentTrendsQueryResponseApiOutput = zod.output<typeof ExperimentTrendsQueryResponseApi>

export const TracesQueryResponseApi = zod.object({
    columns: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(LLMTraceApi),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type TracesQueryResponseApi = zod.input<typeof TracesQueryResponseApi>
export type TracesQueryResponseApiOutput = zod.output<typeof TracesQueryResponseApi>

export const TraceQueryResponseApi = zod.object({
    columns: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: zod.array(LLMTraceApi),
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type TraceQueryResponseApi = zod.input<typeof TraceQueryResponseApi>
export type TraceQueryResponseApiOutput = zod.output<typeof TraceQueryResponseApi>

export const BreakdownAttributionTypeApi = zod.enum(['first_touch', 'last_touch', 'all_events', 'step'])

export type BreakdownAttributionTypeApi = zod.input<typeof BreakdownAttributionTypeApi>
export type BreakdownAttributionTypeApiOutput = zod.output<typeof BreakdownAttributionTypeApi>

export const FunnelExclusionEventsNodeApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type FunnelExclusionEventsNodeApi = zod.input<typeof FunnelExclusionEventsNodeApi>
export type FunnelExclusionEventsNodeApiOutput = zod.output<typeof FunnelExclusionEventsNodeApi>

export const FunnelExclusionActionsNodeApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type FunnelExclusionActionsNodeApi = zod.input<typeof FunnelExclusionActionsNodeApi>
export type FunnelExclusionActionsNodeApiOutput = zod.output<typeof FunnelExclusionActionsNodeApi>

export const StepOrderValueApi = zod.enum(['strict', 'unordered', 'ordered'])

export type StepOrderValueApi = zod.input<typeof StepOrderValueApi>
export type StepOrderValueApiOutput = zod.output<typeof StepOrderValueApi>

export const FunnelStepReferenceApi = zod.enum(['total', 'previous'])

export type FunnelStepReferenceApi = zod.input<typeof FunnelStepReferenceApi>
export type FunnelStepReferenceApiOutput = zod.output<typeof FunnelStepReferenceApi>

export const FunnelVizTypeApi = zod.enum(['steps', 'time_to_convert', 'trends', 'flow'])

export type FunnelVizTypeApi = zod.input<typeof FunnelVizTypeApi>
export type FunnelVizTypeApiOutput = zod.output<typeof FunnelVizTypeApi>

export const FunnelConversionWindowTimeUnitApi = zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month'])

export type FunnelConversionWindowTimeUnitApi = zod.input<typeof FunnelConversionWindowTimeUnitApi>
export type FunnelConversionWindowTimeUnitApiOutput = zod.output<typeof FunnelConversionWindowTimeUnitApi>

export const FunnelLayoutApi = zod.enum(['horizontal', 'vertical'])

export type FunnelLayoutApi = zod.input<typeof FunnelLayoutApi>
export type FunnelLayoutApiOutput = zod.output<typeof FunnelLayoutApi>

export const AggregationPropertyTypeApi = zod.enum(['event', 'person', 'data_warehouse'])

export type AggregationPropertyTypeApi = zod.input<typeof AggregationPropertyTypeApi>
export type AggregationPropertyTypeApiOutput = zod.output<typeof AggregationPropertyTypeApi>

export const AggregationTypeApi = zod.enum(['count', 'sum', 'avg'])

export type AggregationTypeApi = zod.input<typeof AggregationTypeApi>
export type AggregationTypeApiOutput = zod.output<typeof AggregationTypeApi>

export const RetentionDashboardDisplayTypeApi = zod.enum(['table_only', 'graph_only', 'all'])

export type RetentionDashboardDisplayTypeApi = zod.input<typeof RetentionDashboardDisplayTypeApi>
export type RetentionDashboardDisplayTypeApiOutput = zod.output<typeof RetentionDashboardDisplayTypeApi>

export const MeanRetentionCalculationApi = zod.enum(['simple', 'weighted', 'none'])

export type MeanRetentionCalculationApi = zod.input<typeof MeanRetentionCalculationApi>
export type MeanRetentionCalculationApiOutput = zod.output<typeof MeanRetentionCalculationApi>

export const RetentionPeriodApi = zod.enum(['Hour', 'Day', 'Week', 'Month'])

export type RetentionPeriodApi = zod.input<typeof RetentionPeriodApi>
export type RetentionPeriodApiOutput = zod.output<typeof RetentionPeriodApi>

export const RetentionReferenceApi = zod.enum(['total', 'previous'])

export type RetentionReferenceApi = zod.input<typeof RetentionReferenceApi>
export type RetentionReferenceApiOutput = zod.output<typeof RetentionReferenceApi>

export const RetentionTypeApi = zod.enum([
    'retention_recurring',
    'retention_first_time',
    'retention_first_ever_occurrence',
])

export type RetentionTypeApi = zod.input<typeof RetentionTypeApi>
export type RetentionTypeApiOutput = zod.output<typeof RetentionTypeApi>

export const RetentionEntityApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type RetentionEntityApi = zod.input<typeof RetentionEntityApi>
export type RetentionEntityApiOutput = zod.output<typeof RetentionEntityApi>

export const TimeWindowModeApi = zod.enum(['strict_calendar_dates', '24_hour_windows'])

export type TimeWindowModeApi = zod.input<typeof TimeWindowModeApi>
export type TimeWindowModeApiOutput = zod.output<typeof TimeWindowModeApi>

export const FunnelPathTypeApi = zod.enum([
    'funnel_path_before_step',
    'funnel_path_between_steps',
    'funnel_path_after_step',
])

export type FunnelPathTypeApi = zod.input<typeof FunnelPathTypeApi>
export type FunnelPathTypeApiOutput = zod.output<typeof FunnelPathTypeApi>

export const HrefMatchingApi = zod.union([
    zod.literal('contains'),
    zod.literal('exact'),
    zod.literal('regex'),
    zod.literal(null),
])

export type HrefMatchingApi = zod.input<typeof HrefMatchingApi>
export type HrefMatchingApiOutput = zod.output<typeof HrefMatchingApi>

export const TextMatchingApi = zod.union([
    zod.literal('contains'),
    zod.literal('exact'),
    zod.literal('regex'),
    zod.literal(null),
])

export type TextMatchingApi = zod.input<typeof TextMatchingApi>
export type TextMatchingApiOutput = zod.output<typeof TextMatchingApi>

export const UrlMatchingApi = zod.union([
    zod.literal('contains'),
    zod.literal('exact'),
    zod.literal('regex'),
    zod.literal(null),
])

export type UrlMatchingApi = zod.input<typeof UrlMatchingApi>
export type UrlMatchingApiOutput = zod.output<typeof UrlMatchingApi>

export const CompareApi = zod.enum(['current', 'previous'])

export type CompareApi = zod.input<typeof CompareApi>
export type CompareApiOutput = zod.output<typeof CompareApi>

export const FunnelCorrelationQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type FunnelCorrelationQueryApi = zod.input<typeof FunnelCorrelationQueryApi>
export type FunnelCorrelationQueryApiOutput = zod.output<typeof FunnelCorrelationQueryApi>

export const ExperimentEventExposureConfigApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentEventExposureConfigApi = zod.input<typeof ExperimentEventExposureConfigApi>
export type ExperimentEventExposureConfigApiOutput = zod.output<typeof ExperimentEventExposureConfigApi>

export const MultipleVariantHandlingApi = zod.enum(['exclude', 'first_seen'])

export type MultipleVariantHandlingApi = zod.input<typeof MultipleVariantHandlingApi>
export type MultipleVariantHandlingApiOutput = zod.output<typeof MultipleVariantHandlingApi>

export const ExperimentQueryApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentQueryApi = zod.input<typeof ExperimentQueryApi>
export type ExperimentQueryApiOutput = zod.output<typeof ExperimentQueryApi>

export const RetentionEntityKindApi = zod.enum(['ActionsNode', 'EventsNode'])

export type RetentionEntityKindApi = zod.input<typeof RetentionEntityKindApi>
export type RetentionEntityKindApiOutput = zod.output<typeof RetentionEntityKindApi>

export const EntityTypeApi = zod.enum(['actions', 'events', 'data_warehouse', 'new_entity', 'groups'])

export type EntityTypeApi = zod.input<typeof EntityTypeApi>
export type EntityTypeApiOutput = zod.output<typeof EntityTypeApi>

export const FunnelCorrelationResultsTypeApi = zod.enum(['events', 'properties', 'event_with_properties'])

export type FunnelCorrelationResultsTypeApi = zod.input<typeof FunnelCorrelationResultsTypeApi>
export type FunnelCorrelationResultsTypeApiOutput = zod.output<typeof FunnelCorrelationResultsTypeApi>

export const CorrelationTypeApi = zod.enum(['success', 'failure'])

export type CorrelationTypeApi = zod.input<typeof CorrelationTypeApi>
export type CorrelationTypeApiOutput = zod.output<typeof CorrelationTypeApi>

export const EventDefinitionApi = zod.object({
    elements: zod.array(zod.unknown()),
    event: zod.string(),
    properties: zod.record(zod.string(), zod.unknown()),
})

export type EventDefinitionApi = zod.input<typeof EventDefinitionApi>
export type EventDefinitionApiOutput = zod.output<typeof EventDefinitionApi>

export const EventOddsRatioSerializedApi = zod.object({
    correlation_type: CorrelationTypeApi,
    event: EventDefinitionApi,
    failure_count: zod.number(),
    odds_ratio: zod.number(),
    success_count: zod.number(),
})

export type EventOddsRatioSerializedApi = zod.input<typeof EventOddsRatioSerializedApi>
export type EventOddsRatioSerializedApiOutput = zod.output<typeof EventOddsRatioSerializedApi>

export const FunnelCorrelationResultApi = zod.object({
    events: zod.array(EventOddsRatioSerializedApi),
    skewed: zod.boolean(),
})

export type FunnelCorrelationResultApi = zod.input<typeof FunnelCorrelationResultApi>
export type FunnelCorrelationResultApiOutput = zod.output<typeof FunnelCorrelationResultApi>

export const FunnelCorrelationResponseApi = zod.object({
    columns: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    error: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe("Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise."),
    hasMore: zod.union([zod.boolean(), zod.null()]).optional(),
    hogql: zod.union([zod.string(), zod.null()]).optional().describe('Generated HogQL query.'),
    limit: zod.union([zod.number(), zod.null()]).optional(),
    modifiers: zod
        .union([HogQLQueryModifiersApi, zod.null()])
        .optional()
        .describe('Modifiers used when performing the query'),
    offset: zod.union([zod.number(), zod.null()]).optional(),
    query_status: zod
        .union([QueryStatusApi, zod.null()])
        .optional()
        .describe('Query status indicates whether next to the provided data, a query is still running.'),
    resolved_compare_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The resolved previous\/comparison period date range, when comparing against another period'),
    resolved_date_range: zod
        .union([ResolvedDateRangeResponseApi, zod.null()])
        .optional()
        .describe('The date range used for the query'),
    results: FunnelCorrelationResultApi,
    timings: zod
        .union([zod.array(QueryTimingApi), zod.null()])
        .optional()
        .describe('Measured timings for different parts of the query generation process'),
    types: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
    used_data_warehouse_sources: zod
        .union([zod.array(DataWarehouseSourceUsageApi), zod.null()])
        .optional()
        .describe('Connector-synced data warehouse sources referenced by this query, if any.'),
    warnings: zod
        .union([zod.array(zod.union([DataWarehouseSyncWarningApi, AccessControlFilterWarningApi])), zod.null()])
        .optional()
        .describe(
            "Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access."
        ),
})

export type FunnelCorrelationResponseApi = zod.input<typeof FunnelCorrelationResponseApi>
export type FunnelCorrelationResponseApiOutput = zod.output<typeof FunnelCorrelationResponseApi>

export const ExperimentMeanMetricApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentMeanMetricApi = zod.input<typeof ExperimentMeanMetricApi>
export type ExperimentMeanMetricApiOutput = zod.output<typeof ExperimentMeanMetricApi>

export const ExperimentFunnelMetricApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentFunnelMetricApi = zod.input<typeof ExperimentFunnelMetricApi>
export type ExperimentFunnelMetricApiOutput = zod.output<typeof ExperimentFunnelMetricApi>

export const ExperimentRatioMetricApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentRatioMetricApi = zod.input<typeof ExperimentRatioMetricApi>
export type ExperimentRatioMetricApiOutput = zod.output<typeof ExperimentRatioMetricApi>

export const ExperimentRetentionMetricApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentRetentionMetricApi = zod.input<typeof ExperimentRetentionMetricApi>
export type ExperimentRetentionMetricApiOutput = zod.output<typeof ExperimentRetentionMetricApi>

export const PrecomputationModeApi = zod.enum(['precomputed', 'direct'])

export type PrecomputationModeApi = zod.input<typeof PrecomputationModeApi>
export type PrecomputationModeApiOutput = zod.output<typeof PrecomputationModeApi>

export const ExperimentQueryResponseApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentQueryResponseApi = zod.input<typeof ExperimentQueryResponseApi>
export type ExperimentQueryResponseApiOutput = zod.output<typeof ExperimentQueryResponseApi>

export const ExperimentMetricGoalApi = zod.enum(['increase', 'decrease'])

export type ExperimentMetricGoalApi = zod.input<typeof ExperimentMetricGoalApi>
export type ExperimentMetricGoalApiOutput = zod.output<typeof ExperimentMetricGoalApi>

export const ExperimentDataWarehouseNodeApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ExperimentDataWarehouseNodeApi = zod.input<typeof ExperimentDataWarehouseNodeApi>
export type ExperimentDataWarehouseNodeApiOutput = zod.output<typeof ExperimentDataWarehouseNodeApi>

export const experimentMetricOutlierHandlingApiLowerBoundPercentileOneMin = 0
export const experimentMetricOutlierHandlingApiLowerBoundPercentileOneMax = 1

export const experimentMetricOutlierHandlingApiUpperBoundPercentileOneMin = 0
export const experimentMetricOutlierHandlingApiUpperBoundPercentileOneMax = 1

export const ExperimentMetricOutlierHandlingApi = zod.object({
    ignore_zeros: zod.union([zod.boolean(), zod.null()]).optional(),
    lower_bound_percentile: zod
        .union([
            zod
                .number()
                .min(experimentMetricOutlierHandlingApiLowerBoundPercentileOneMin)
                .max(experimentMetricOutlierHandlingApiLowerBoundPercentileOneMax),
            zod.null(),
        ])
        .optional()
        .describe('Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile).'),
    upper_bound_percentile: zod
        .union([
            zod
                .number()
                .min(experimentMetricOutlierHandlingApiUpperBoundPercentileOneMin)
                .max(experimentMetricOutlierHandlingApiUpperBoundPercentileOneMax),
            zod.null(),
        ])
        .optional()
        .describe('Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile).'),
})

export type ExperimentMetricOutlierHandlingApi = zod.input<typeof ExperimentMetricOutlierHandlingApi>
export type ExperimentMetricOutlierHandlingApiOutput = zod.output<typeof ExperimentMetricOutlierHandlingApi>

export const StartHandlingApi = zod.enum(['first_seen', 'last_seen'])

export type StartHandlingApi = zod.input<typeof StartHandlingApi>
export type StartHandlingApiOutput = zod.output<typeof StartHandlingApi>

export const SessionDataApi = zod.object({
    event_uuid: zod.string(),
    person_id: zod.string(),
    session_id: zod.string(),
    timestamp: zod.string(),
})

export type SessionDataApi = zod.input<typeof SessionDataApi>
export type SessionDataApiOutput = zod.output<typeof SessionDataApi>

export const ExperimentStatsValidationFailureApi = zod.enum([
    'not-enough-exposures',
    'baseline-mean-is-zero',
    'not-enough-metric-data',
])

export type ExperimentStatsValidationFailureApi = zod.input<typeof ExperimentStatsValidationFailureApi>
export type ExperimentStatsValidationFailureApiOutput = zod.output<typeof ExperimentStatsValidationFailureApi>

export const ExperimentStatsBaseValidatedApi = zod.object({
    covariate_sum: zod.union([zod.number(), zod.null()]).optional(),
    covariate_sum_product: zod.union([zod.number(), zod.null()]).optional(),
    covariate_sum_squares: zod.union([zod.number(), zod.null()]).optional(),
    denominator_sum: zod.union([zod.number(), zod.null()]).optional(),
    denominator_sum_squares: zod.union([zod.number(), zod.null()]).optional(),
    key: zod.string(),
    number_of_samples: zod.number(),
    numerator_denominator_sum_product: zod.union([zod.number(), zod.null()]).optional(),
    step_counts: zod.union([zod.array(zod.number()), zod.null()]).optional(),
    step_sessions: zod.union([zod.array(zod.array(SessionDataApi)), zod.null()]).optional(),
    sum: zod.number(),
    sum_squares: zod.number(),
    validation_failures: zod.union([zod.array(ExperimentStatsValidationFailureApi), zod.null()]).optional(),
})

export type ExperimentStatsBaseValidatedApi = zod.input<typeof ExperimentStatsBaseValidatedApi>
export type ExperimentStatsBaseValidatedApiOutput = zod.output<typeof ExperimentStatsBaseValidatedApi>

export const experimentVariantResultFrequentistApiConfidenceIntervalOneMin = 2
export const experimentVariantResultFrequentistApiConfidenceIntervalOneMax = 2

export const experimentVariantResultFrequentistApiMethodDefault = `frequentist`

export const ExperimentVariantResultFrequentistApi = zod.object({
    confidence_interval: zod
        .union([
            zod
                .array(zod.number())
                .min(experimentVariantResultFrequentistApiConfidenceIntervalOneMin)
                .max(experimentVariantResultFrequentistApiConfidenceIntervalOneMax),
            zod.null(),
        ])
        .optional(),
    covariate_sum: zod.union([zod.number(), zod.null()]).optional(),
    covariate_sum_product: zod.union([zod.number(), zod.null()]).optional(),
    covariate_sum_squares: zod.union([zod.number(), zod.null()]).optional(),
    denominator_sum: zod.union([zod.number(), zod.null()]).optional(),
    denominator_sum_squares: zod.union([zod.number(), zod.null()]).optional(),
    key: zod.string(),
    method: zod.literal('frequentist').default(experimentVariantResultFrequentistApiMethodDefault),
    number_of_samples: zod.number(),
    numerator_denominator_sum_product: zod.union([zod.number(), zod.null()]).optional(),
    p_value: zod.union([zod.number(), zod.null()]).optional(),
    significant: zod.union([zod.boolean(), zod.null()]).optional(),
    step_counts: zod.union([zod.array(zod.number()), zod.null()]).optional(),
    step_sessions: zod.union([zod.array(zod.array(SessionDataApi)), zod.null()]).optional(),
    sum: zod.number(),
    sum_squares: zod.number(),
    validation_failures: zod.union([zod.array(ExperimentStatsValidationFailureApi), zod.null()]).optional(),
})

export type ExperimentVariantResultFrequentistApi = zod.input<typeof ExperimentVariantResultFrequentistApi>
export type ExperimentVariantResultFrequentistApiOutput = zod.output<typeof ExperimentVariantResultFrequentistApi>

export const experimentVariantResultBayesianApiCredibleIntervalOneMin = 2
export const experimentVariantResultBayesianApiCredibleIntervalOneMax = 2

export const experimentVariantResultBayesianApiMethodDefault = `bayesian`

export const ExperimentVariantResultBayesianApi = zod.object({
    chance_to_win: zod.union([zod.number(), zod.null()]).optional(),
    covariate_sum: zod.union([zod.number(), zod.null()]).optional(),
    covariate_sum_product: zod.union([zod.number(), zod.null()]).optional(),
    covariate_sum_squares: zod.union([zod.number(), zod.null()]).optional(),
    credible_interval: zod
        .union([
            zod
                .array(zod.number())
                .min(experimentVariantResultBayesianApiCredibleIntervalOneMin)
                .max(experimentVariantResultBayesianApiCredibleIntervalOneMax),
            zod.null(),
        ])
        .optional(),
    denominator_sum: zod.union([zod.number(), zod.null()]).optional(),
    denominator_sum_squares: zod.union([zod.number(), zod.null()]).optional(),
    key: zod.string(),
    method: zod.literal('bayesian').default(experimentVariantResultBayesianApiMethodDefault),
    number_of_samples: zod.number(),
    numerator_denominator_sum_product: zod.union([zod.number(), zod.null()]).optional(),
    significant: zod.union([zod.boolean(), zod.null()]).optional(),
    step_counts: zod.union([zod.array(zod.number()), zod.null()]).optional(),
    step_sessions: zod.union([zod.array(zod.array(SessionDataApi)), zod.null()]).optional(),
    sum: zod.number(),
    sum_squares: zod.number(),
    validation_failures: zod.union([zod.array(ExperimentStatsValidationFailureApi), zod.null()]).optional(),
})

export type ExperimentVariantResultBayesianApi = zod.input<typeof ExperimentVariantResultBayesianApi>
export type ExperimentVariantResultBayesianApiOutput = zod.output<typeof ExperimentVariantResultBayesianApi>

export const ExperimentBreakdownResultApi = zod.object({
    baseline: ExperimentStatsBaseValidatedApi.describe('Control variant stats for this breakdown'),
    breakdown_value: zod
        .array(zod.union([zod.string(), zod.number(), zod.number()]))
        .describe(
            'The breakdown values as an array (e.g., [\"MacOS\", \"Chrome\"] for multi-breakdown, [\"Chrome\"] for single) Although `BreakdownKeyType` could be an array, we only use the array form for the breakdown_value. The way `BreakdownKeyType` is defined is problematic. It should be treated as a primitive and allow for the types using it to define if it\'s and array or an optional value.'
        ),
    variants: zod
        .union([zod.array(ExperimentVariantResultFrequentistApi), zod.array(ExperimentVariantResultBayesianApi)])
        .describe('Test variant results with statistical comparisons for this breakdown'),
})

export type ExperimentBreakdownResultApi = zod.input<typeof ExperimentBreakdownResultApi>
export type ExperimentBreakdownResultApiOutput = zod.output<typeof ExperimentBreakdownResultApi>
