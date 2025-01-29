import { DataColorToken } from 'lib/colors'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import {
    AnyFilterLike,
    AnyPersonScopeFilter,
    AnyPropertyFilter,
    BaseMathType,
    BreakdownKeyType,
    BreakdownType,
    ChartDisplayCategory,
    ChartDisplayType,
    CountPerActorMathType,
    EventPropertyFilter,
    EventType,
    FilterLogicalOperator,
    FilterType,
    FunnelMathType,
    FunnelsFilterType,
    GroupMathType,
    HogQLMathType,
    InsightShortId,
    InsightType,
    IntervalType,
    LifecycleFilterType,
    LifecycleToggle,
    LogEntryPropertyFilter,
    PathsFilterType,
    PersonPropertyFilter,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyMathType,
    PropertyOperator,
    RetentionFilterType,
    SessionPropertyFilter,
    SessionRecordingType,
    StickinessFilterType,
    TrendsFilterType,
} from '~/types'

import { integer, numerical_key } from './type-utils'

export { ChartDisplayCategory }

/**
 * PostHog Query Schema definition.
 *
 * This file acts as the source of truth for:
 *
 * - frontend/src/queries/schema.json
 *   - generated from typescript via "pnpm run schema:build:json"
 *
 * - posthog/schema.py
 *   - generated from json the above json via "pnpm run schema:build:python"
 * */

export enum NodeKind {
    // Data nodes
    EventsNode = 'EventsNode',
    ActionsNode = 'ActionsNode',
    DataWarehouseNode = 'DataWarehouseNode',
    EventsQuery = 'EventsQuery',
    PersonsNode = 'PersonsNode',
    HogQuery = 'HogQuery',
    HogQLQuery = 'HogQLQuery',
    HogQLMetadata = 'HogQLMetadata',
    HogQLAutocomplete = 'HogQLAutocomplete',
    ActorsQuery = 'ActorsQuery',
    FunnelsActorsQuery = 'FunnelsActorsQuery',
    FunnelCorrelationActorsQuery = 'FunnelCorrelationActorsQuery',
    SessionsTimelineQuery = 'SessionsTimelineQuery',
    RecordingsQuery = 'RecordingsQuery',
    SessionAttributionExplorerQuery = 'SessionAttributionExplorerQuery',
    ErrorTrackingQuery = 'ErrorTrackingQuery',

    // Interface nodes
    DataTableNode = 'DataTableNode',
    DataVisualizationNode = 'DataVisualizationNode',
    SavedInsightNode = 'SavedInsightNode',
    InsightVizNode = 'InsightVizNode',

    TrendsQuery = 'TrendsQuery',
    FunnelsQuery = 'FunnelsQuery',
    RetentionQuery = 'RetentionQuery',
    PathsQuery = 'PathsQuery',
    StickinessQuery = 'StickinessQuery',
    LifecycleQuery = 'LifecycleQuery',
    InsightActorsQuery = 'InsightActorsQuery',
    InsightActorsQueryOptions = 'InsightActorsQueryOptions',
    FunnelCorrelationQuery = 'FunnelCorrelationQuery',

    // Web analytics + Web Vitals queries
    WebOverviewQuery = 'WebOverviewQuery',
    WebStatsTableQuery = 'WebStatsTableQuery',
    WebExternalClicksTableQuery = 'WebExternalClicksTableQuery',
    WebGoalsQuery = 'WebGoalsQuery',
    WebVitalsQuery = 'WebVitalsQuery',
    WebVitalsPathBreakdownQuery = 'WebVitalsPathBreakdownQuery',

    // Experiment queries
    ExperimentFunnelsQuery = 'ExperimentFunnelsQuery',
    ExperimentTrendsQuery = 'ExperimentTrendsQuery',

    // Database metadata
    DatabaseSchemaQuery = 'DatabaseSchemaQuery',

    // AI queries
    SuggestedQuestionsQuery = 'SuggestedQuestionsQuery',
    TeamTaxonomyQuery = 'TeamTaxonomyQuery',
    EventTaxonomyQuery = 'EventTaxonomyQuery',
    ActorsPropertyTaxonomyQuery = 'ActorsPropertyTaxonomyQuery',
    TracesQuery = 'TracesQuery',
}

export type AnyDataNode =
    | EventsNode // never queried directly
    | ActionsNode // old actions API endpoint
    | PersonsNode // old persons API endpoint
    | EventsQuery
    | ActorsQuery
    | InsightActorsQuery
    | InsightActorsQueryOptions
    | SessionsTimelineQuery
    | HogQuery
    | HogQLQuery
    | HogQLMetadata
    | HogQLAutocomplete
    | WebOverviewQuery
    | WebStatsTableQuery
    | WebExternalClicksTableQuery
    | WebGoalsQuery
    | WebVitalsQuery
    | WebVitalsPathBreakdownQuery
    | SessionAttributionExplorerQuery
    | ErrorTrackingQuery
    | ExperimentFunnelsQuery
    | ExperimentTrendsQuery
    | RecordingsQuery
    | TracesQuery

/**
 * @discriminator kind
 */
export type QuerySchema =
    // Data nodes (see utils.ts)
    | EventsNode // never queried directly
    | ActionsNode // old actions API endpoint
    | PersonsNode // old persons API endpoint
    | DataWarehouseNode
    | EventsQuery
    | ActorsQuery
    | InsightActorsQuery
    | InsightActorsQueryOptions
    | SessionsTimelineQuery
    | HogQuery
    | HogQLQuery
    | HogQLMetadata
    | HogQLAutocomplete
    | SessionAttributionExplorerQuery
    | ErrorTrackingQuery
    | ExperimentFunnelsQuery
    | ExperimentTrendsQuery

    // Web Analytics + Web Vitals
    | WebOverviewQuery
    | WebStatsTableQuery
    | WebExternalClicksTableQuery
    | WebGoalsQuery
    | WebVitalsQuery
    | WebVitalsPathBreakdownQuery

    // Interface nodes
    | DataVisualizationNode
    | DataTableNode
    | SavedInsightNode
    | InsightVizNode

    // Classic insights
    | TrendsQuery
    | FunnelsQuery
    | RetentionQuery
    | PathsQuery
    | StickinessQuery
    | LifecycleQuery
    | FunnelCorrelationQuery

    // Misc
    | DatabaseSchemaQuery

    // AI
    | SuggestedQuestionsQuery
    | TeamTaxonomyQuery
    | EventTaxonomyQuery
    | ActorsPropertyTaxonomyQuery
    | TracesQuery

// Keep this, because QuerySchema itself will be collapsed as it is used in other models
export type QuerySchemaRoot = QuerySchema

// Dynamically make a union type out of all the types in all `response` fields in QuerySchema
type QueryResponseType<T> = T extends { response?: infer R } ? { response: R } : never
type QueryAllResponses = QueryResponseType<QuerySchema>
export type QueryResponseAlternative = QueryAllResponses['response']

/**
 * Node base class, everything else inherits from here.
 * @internal - no need to emit to schema.json.
 */
export interface Node<R extends Record<string, any> = Record<string, any>> {
    kind: NodeKind
    /** @internal Don't use this property at runtime, it's here for typing. */
    response?: R
}

// Data nodes

export type AnyResponseType =
    | Record<string, any>
    | HogQueryResponse
    | HogQLQueryResponse
    | HogQLMetadataResponse
    | HogQLAutocompleteResponse
    | EventsNode['response']
    | EventsQueryResponse
    | ErrorTrackingQueryResponse

/** @internal - no need to emit to schema.json. */
export interface DataNode<R extends Record<string, any> = Record<string, any>> extends Node<R> {
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiers
}

/** HogQL Query Options are automatically set per team. However, they can be overridden in the query. */
export interface HogQLQueryModifiers {
    personsOnEventsMode?:
        | 'disabled' // `disabled` is deprecated and set for removal - `person_id_override_properties_joined` is its faster functional equivalent
        | 'person_id_no_override_properties_on_events'
        | 'person_id_override_properties_on_events'
        | 'person_id_override_properties_joined'
    personsArgMaxVersion?: 'auto' | 'v1' | 'v2'
    inCohortVia?: 'auto' | 'leftjoin' | 'subquery' | 'leftjoin_conjoined'
    materializationMode?: 'auto' | 'legacy_null_as_string' | 'legacy_null_as_null' | 'disabled'
    optimizeJoinedFilters?: boolean
    dataWarehouseEventsModifiers?: DataWarehouseEventsModifier[]
    debug?: boolean
    s3TableUseInvalidColumns?: boolean
    personsJoinMode?: 'inner' | 'left'
    bounceRatePageViewMode?: 'count_pageviews' | 'uniq_urls' | 'uniq_page_screen_autocaptures'
    bounceRateDurationSeconds?: number
    sessionTableVersion?: 'auto' | 'v1' | 'v2'
    propertyGroupsMode?: 'enabled' | 'disabled' | 'optimized'
    useMaterializedViews?: boolean
    customChannelTypeRules?: CustomChannelRule[]
}

export interface DataWarehouseEventsModifier {
    table_name: string
    timestamp_field: string
    distinct_id_field: string
    id_field: string
}

export interface HogQLQueryResponse extends AnalyticsQueryResponseBase<any[]> {
    /** Input query string */
    query?: string
    /** Executed ClickHouse query */
    clickhouse?: string
    /** Returned columns */
    columns?: any[]
    /** Types of returned columns */
    types?: any[]
    /** Query explanation output */
    explain?: string[]
    /** Query metadata output */
    metadata?: HogQLMetadataResponse
    hasMore?: boolean
    limit?: integer
    offset?: integer
}

export type CachedHogQLQueryResponse = CachedQueryResponse<HogQLQueryResponse>

/** Filters object that will be converted to a HogQL {filters} placeholder */
export interface HogQLFilters {
    properties?: AnyPropertyFilter[]
    dateRange?: DateRange
    filterTestAccounts?: boolean
}

export interface HogQLVariable {
    variableId: string
    code_name: string
    value?: any
}

export interface HogQLQuery extends DataNode<HogQLQueryResponse> {
    kind: NodeKind.HogQLQuery
    query: string
    filters?: HogQLFilters
    /** Variables to be subsituted into the query */
    variables?: Record<string, HogQLVariable>
    /** Constant values that can be referenced with the {placeholder} syntax in the query */
    values?: Record<string, any>
    /** @deprecated use modifiers.debug instead */
    explain?: boolean
}

export interface HogQueryResponse {
    results: any
    bytecode?: any[]
    coloredBytecode?: any[]
    stdout?: string
    query_status?: never
}

export interface HogQuery extends DataNode<HogQueryResponse> {
    kind: NodeKind.HogQuery
    code?: string
}

export interface RecordingsQueryResponse {
    results: SessionRecordingType[]
    has_next: boolean
}

export type RecordingOrder =
    | 'duration'
    | 'recording_duration'
    | 'inactive_seconds'
    | 'active_seconds'
    | 'start_time'
    | 'console_error_count'
    | 'click_count'
    | 'keypress_count'
    | 'mouse_activity_count'
    | 'activity_score'

export interface RecordingsQuery extends DataNode<RecordingsQueryResponse> {
    kind: NodeKind.RecordingsQuery
    /**
     * @default "-3d"
     * */
    date_from?: string | null
    date_to?: string | null
    events?: FilterType['events']
    actions?: FilterType['actions']
    properties?: AnyPropertyFilter[]
    console_log_filters?: LogEntryPropertyFilter[]
    having_predicates?: AnyPropertyFilter[] // duration and snapshot_source filters
    filter_test_accounts?: boolean
    /**
     * @default "AND"
     * */
    operand?: FilterLogicalOperator
    session_ids?: string[]
    person_uuid?: string
    /**
     * @default "start_time"
     * */
    order?: RecordingOrder
    limit?: integer
    offset?: integer
    user_modified_filters?: Record<string, any>
}

export interface HogQLNotice {
    start?: integer
    end?: integer
    message: string
    fix?: string
}

export interface HogQLMetadataResponse {
    query?: string
    isValid?: boolean
    isValidView?: boolean
    errors: HogQLNotice[]
    warnings: HogQLNotice[]
    notices: HogQLNotice[]
    query_status?: never
    table_names?: string[]
}

export type AutocompleteCompletionItemKind =
    | 'Method'
    | 'Function'
    | 'Constructor'
    | 'Field'
    | 'Variable'
    | 'Class'
    | 'Struct'
    | 'Interface'
    | 'Module'
    | 'Property'
    | 'Event'
    | 'Operator'
    | 'Unit'
    | 'Value'
    | 'Constant'
    | 'Enum'
    | 'EnumMember'
    | 'Keyword'
    | 'Text'
    | 'Color'
    | 'File'
    | 'Reference'
    | 'Customcolor'
    | 'Folder'
    | 'TypeParameter'
    | 'User'
    | 'Issue'
    | 'Snippet'

export interface AutocompleteCompletionItem {
    /**
     * The label of this completion item. By default
     * this is also the text that is inserted when selecting
     * this completion.
     */
    label: string
    /**
     * A human-readable string that represents a doc-comment.
     */
    documentation?: string
    /**
     * A human-readable string with additional information
     * about this item, like type or symbol information.
     */
    detail?: string
    /**
     * A string or snippet that should be inserted in a document when selecting
     * this completion.
     */
    insertText: string
    /**
     * The kind of this completion item. Based on the kind
     * an icon is chosen by the editor.
     */
    kind: AutocompleteCompletionItemKind
}

export interface HogQLAutocompleteResponse {
    suggestions: AutocompleteCompletionItem[]
    /** Whether or not the suggestions returned are complete */
    incomplete_list: boolean
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTiming[]
    query_status?: never
}

export enum HogLanguage {
    hog = 'hog',
    hogJson = 'hogJson',
    hogQL = 'hogQL',
    hogQLExpr = 'hogQLExpr',
    hogTemplate = 'hogTemplate',
}

export interface HogQLMetadata extends DataNode<HogQLMetadataResponse> {
    kind: NodeKind.HogQLMetadata
    /** Language to validate */
    language: HogLanguage
    /** Query to validate */
    query: string
    /** Query within which "expr" and "template" are validated. Defaults to "select * from events" */
    sourceQuery?: AnyDataNode
    /** Extra globals for the query */
    globals?: Record<string, any>
    /** Extra filters applied to query via {filters} */
    filters?: HogQLFilters
    /** Variables to be subsituted into the query */
    variables?: Record<string, HogQLVariable>
    /** Enable more verbose output, usually run from the /debug page */
    debug?: boolean
}

export interface HogQLAutocomplete extends DataNode<HogQLAutocompleteResponse> {
    kind: NodeKind.HogQLAutocomplete
    /** Language to validate */
    language: HogLanguage
    /** Query to validate */
    query: string
    /** Query in whose context to validate. */
    sourceQuery?: AnyDataNode
    /** Global values in scope */
    globals?: Record<string, any>
    /** Table to validate the expression against */
    filters?: HogQLFilters
    /**
     * Start position of the editor word
     */
    startPosition: integer
    /**
     * End position of the editor word
     */
    endPosition: integer
}

export type MathType =
    | BaseMathType
    | FunnelMathType
    | PropertyMathType
    | CountPerActorMathType
    | GroupMathType
    | HogQLMathType

export interface EntityNode extends Node {
    name?: string
    custom_name?: string
    math?: MathType
    math_property?: string
    math_property_type?: string
    math_hogql?: string
    math_group_type_index?: 0 | 1 | 2 | 3 | 4
    /** Properties configurable in the interface */
    properties?: AnyPropertyFilter[]
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?: AnyPropertyFilter[]
}

export interface EventsNode extends EntityNode {
    kind: NodeKind.EventsNode
    /** The event or `null` for all events. */
    event?: string | null
    limit?: integer
    /** Columns to order by */
    orderBy?: string[]
}

export interface DataWarehouseNode extends EntityNode {
    id: string
    kind: NodeKind.DataWarehouseNode
    id_field: string
    table_name: string
    timestamp_field: string
    distinct_id_field: string
}

export interface ActionsNode extends EntityNode {
    kind: NodeKind.ActionsNode
    id: integer
}

export type AnyEntityNode = EventsNode | ActionsNode | DataWarehouseNode

export interface QueryTiming {
    /** Key. Shortened to 'k' to save on data. */
    k: string
    /** Time in seconds. Shortened to 't' to save on data. */
    t: number
}
export interface EventsQueryResponse extends AnalyticsQueryResponseBase<any[][]> {
    columns: any[]
    types: string[]
    hogql: string
    hasMore?: boolean
    limit?: integer
    offset?: integer
}

export type CachedEventsQueryResponse = CachedQueryResponse<EventsQueryResponse>

export interface EventsQueryPersonColumn {
    uuid: string
    created_at: string
    properties: {
        name?: string
        email?: string
    }
    distinct_id: string
}

export interface EventsQuery extends DataNode<EventsQueryResponse> {
    kind: NodeKind.EventsQuery
    /** Return a limited set of data. Required. */
    select: HogQLExpression[]
    /** HogQL filters to apply on returned data */
    where?: HogQLExpression[]
    /** Properties configurable in the interface */
    properties?: AnyPropertyFilter[]
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?: AnyFilterLike[]
    /** Filter test accounts */
    filterTestAccounts?: boolean
    /** Limit to events matching this string */
    event?: string | null
    /**
     * Number of rows to return
     */
    limit?: integer
    /**
     * Number of rows to skip before returning rows
     */
    offset?: integer
    /**
     * Show events matching a given action
     */
    actionId?: integer
    /** Show events for a given person */
    personId?: string
    /** Only fetch events that happened before this timestamp */
    before?: string
    /** Only fetch events that happened after this timestamp */
    after?: string
    /** Columns to order by */
    orderBy?: string[]
}

/**
 * @deprecated Use `ActorsQuery` instead.
 */
export interface PersonsNode extends DataNode {
    kind: NodeKind.PersonsNode
    search?: string
    cohort?: integer
    distinctId?: string
    /** Properties configurable in the interface */
    properties?: AnyPropertyFilter[]
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?: AnyPropertyFilter[]
    limit?: integer
    offset?: integer
}

// Data table node

export type HasPropertiesNode = EventsNode | EventsQuery | PersonsNode

export interface DataTableNode
    extends Node<
            NonNullable<
                (
                    | EventsNode
                    | EventsQuery
                    | PersonsNode
                    | ActorsQuery
                    | HogQLQuery
                    | WebOverviewQuery
                    | WebStatsTableQuery
                    | WebExternalClicksTableQuery
                    | WebGoalsQuery
                    | WebVitalsQuery
                    | WebVitalsPathBreakdownQuery
                    | SessionAttributionExplorerQuery
                    | ErrorTrackingQuery
                    | ExperimentFunnelsQuery
                    | ExperimentTrendsQuery
                    | TracesQuery
                )['response']
            >
        >,
        DataTableNodeViewProps {
    kind: NodeKind.DataTableNode
    /** Source of the events */
    source:
        | EventsNode
        | EventsQuery
        | PersonsNode
        | ActorsQuery
        | HogQLQuery
        | WebOverviewQuery
        | WebStatsTableQuery
        | WebExternalClicksTableQuery
        | WebGoalsQuery
        | WebVitalsQuery
        | WebVitalsPathBreakdownQuery
        | SessionAttributionExplorerQuery
        | ErrorTrackingQuery
        | ExperimentFunnelsQuery
        | ExperimentTrendsQuery
        | TracesQuery
    /** Columns shown in the table, unless the `source` provides them. */
    columns?: HogQLExpression[]
    /** Columns that aren't shown in the table, even if in columns or returned data */
    hiddenColumns?: HogQLExpression[]
}

export interface GoalLine {
    label: string
    value: number
    displayLabel?: boolean
    borderColor?: string
}

export interface ChartAxis {
    column: string
    settings?: {
        formatting?: ChartSettingsFormatting
        display?: ChartSettingsDisplay
    }
}

export interface ChartSettingsFormatting {
    prefix?: string
    suffix?: string
    style?: 'none' | 'number' | 'percent'
    decimalPlaces?: number
}

export interface ChartSettingsDisplay {
    color?: string
    label?: string
    trendLine?: boolean
    yAxisPosition?: 'left' | 'right'
    displayType?: 'auto' | 'line' | 'bar'
}

export interface YAxisSettings {
    scale?: 'linear' | 'logarithmic'
    /** Whether the Y axis should start at zero */
    startAtZero?: boolean
}

export interface ChartSettings {
    xAxis?: ChartAxis
    yAxis?: ChartAxis[]
    goalLines?: GoalLine[]
    /** Deprecated: use `[left|right]YAxisSettings`. Whether the Y axis should start at zero */
    yAxisAtZero?: boolean
    leftYAxisSettings?: YAxisSettings
    rightYAxisSettings?: YAxisSettings
    /** Whether we fill the bars to 100% in stacked mode */
    stackBars100?: boolean
    seriesBreakdownColumn?: string | null
    showLegend?: boolean
}

export interface ConditionalFormattingRule {
    id: string
    templateId: string
    columnName: string
    bytecode: any[]
    input: string
    color: string
    colorMode?: 'light' | 'dark'
}

export interface TableSettings {
    columns?: ChartAxis[]
    conditionalFormatting?: ConditionalFormattingRule[]
}

export interface DataVisualizationNode extends Node<never> {
    kind: NodeKind.DataVisualizationNode
    source: HogQLQuery
    display?: ChartDisplayType
    chartSettings?: ChartSettings
    tableSettings?: TableSettings
}

interface DataTableNodeViewProps {
    /** Show with most visual options enabled. Used in scenes. */ full?: boolean
    /** Include an event filter above the table (EventsNode only) */
    showEventFilter?: boolean
    /** Include a free text search field (PersonsNode only) */
    showSearch?: boolean
    /** Include a property filter above the table */
    showPropertyFilter?: boolean | TaxonomicFilterGroupType[]
    /** Show filter to exclude test accounts */
    showTestAccountFilters?: boolean
    /** Include a HogQL query editor above HogQL tables */
    showHogQLEditor?: boolean
    /** Show the kebab menu at the end of the row */
    showActions?: boolean
    /** Show date range selector */
    showDateRange?: boolean
    /** Show the export button */
    showExport?: boolean
    /** Show a reload button */
    showReload?: boolean
    /** Show the time it takes to run a query */
    showElapsedTime?: boolean
    /** Show a detailed query timing breakdown */
    showTimings?: boolean
    /** Show a button to configure the table's columns if possible */
    showColumnConfigurator?: boolean
    /** Show a button to configure and persist the table's default columns if possible */
    showPersistentColumnConfigurator?: boolean
    /** Shows a list of saved queries */
    showSavedQueries?: boolean
    /** Can expand row to show raw event data (default: true) */
    expandable?: boolean
    /** Link properties via the URL (default: false) */
    propertiesViaUrl?: boolean
    /** Can the user click on column headers to sort the table? (default: true) */
    allowSorting?: boolean
    /** Show a button to open the current query as a new insight. (default: true) */
    showOpenEditorButton?: boolean
    /** Show a results table */
    showResultsTable?: boolean
    /** Uses the embedded version of LemonTable */
    embedded?: boolean
}

// Saved insight node

export interface SavedInsightNode extends Node<never>, InsightVizNodeViewProps, DataTableNodeViewProps {
    kind: NodeKind.SavedInsightNode
    shortId: InsightShortId
}

// Insight viz node

/** Chart specific rendering options.
 * Use ChartRenderingMetadata for non-serializable values, e.g. onClick handlers
 * @see ChartRenderingMetadata
 * **/
export interface VizSpecificOptions {
    [InsightType.RETENTION]?: {
        hideLineGraph?: boolean
        hideSizeColumn?: boolean
        useSmallLayout?: boolean
    }
    [ChartDisplayType.ActionsPie]?: {
        disableHoverOffset?: boolean
        hideAggregation?: boolean
    }
}

export interface InsightVizNode<T = InsightQueryNode> extends Node<never>, InsightVizNodeViewProps {
    kind: NodeKind.InsightVizNode
    source: T
}

interface InsightVizNodeViewProps {
    /** Show with most visual options enabled. Used in insight scene. */
    full?: boolean
    showHeader?: boolean
    showTable?: boolean
    showCorrelationTable?: boolean
    showLastComputation?: boolean
    showLastComputationRefresh?: boolean
    showFilters?: boolean
    showResults?: boolean
    /** Query is embedded inside another bordered component */
    embedded?: boolean
    suppressSessionAnalysisWarning?: boolean
    hidePersonsModal?: boolean
    vizSpecificOptions?: VizSpecificOptions
}

/** Base class for insight query nodes. Should not be used directly. */
export interface InsightsQueryBase<R extends AnalyticsQueryResponseBase<any>> extends Node<R> {
    /** Date range for the query */
    dateRange?: DateRange
    /**
     * Exclude internal and test users by applying the respective filters
     *
     * @default false
     */
    filterTestAccounts?: boolean
    /**
     * Property filters for all series
     *
     * @default []
     */
    properties?: AnyPropertyFilter[] | PropertyGroupFilter
    /**
     * Groups aggregation
     */
    aggregation_group_type_index?: integer | null
    /** Sampling rate */
    samplingFactor?: number | null
    /** Colors used in the insight's visualization */
    dataColorTheme?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiers
}

/** `TrendsFilterType` minus everything inherited from `FilterType` and `shown_as` */
export type TrendsFilterLegacy = Omit<TrendsFilterType, keyof FilterType | 'shown_as'>

export enum ResultCustomizationBy {
    Value = 'value',
    Position = 'position',
}

export type TrendsFilter = {
    /** @default 1 */
    smoothingIntervals?: integer
    formula?: TrendsFilterLegacy['formula']
    /** @default ActionsLineGraph */
    display?: TrendsFilterLegacy['display']
    /** @default false */
    showLegend?: TrendsFilterLegacy['show_legend']
    /** @default false */
    showAlertThresholdLines?: boolean
    breakdown_histogram_bin_count?: TrendsFilterLegacy['breakdown_histogram_bin_count'] // TODO: fully move into BreakdownFilter
    /** @default numeric */
    aggregationAxisFormat?: TrendsFilterLegacy['aggregation_axis_format']
    aggregationAxisPrefix?: TrendsFilterLegacy['aggregation_axis_prefix']
    aggregationAxisPostfix?: TrendsFilterLegacy['aggregation_axis_postfix']
    decimalPlaces?: TrendsFilterLegacy['decimal_places']
    /** @default false */
    showValuesOnSeries?: TrendsFilterLegacy['show_values_on_series']
    showLabelsOnSeries?: TrendsFilterLegacy['show_labels_on_series']
    /** @default false */
    showPercentStackView?: TrendsFilterLegacy['show_percent_stack_view']
    yAxisScaleType?: TrendsFilterLegacy['y_axis_scale_type']
    hiddenLegendIndexes?: integer[]
    /**
     * Wether result datasets are associated by their values or by their order.
     * @default value
     **/
    resultCustomizationBy?: ResultCustomizationBy
    /** Customizations for the appearance of result datasets. */
    resultCustomizations?:
        | Record<string, ResultCustomizationByValue>
        | Record<numerical_key, ResultCustomizationByPosition>
    /** Goal Lines */
    goalLines?: GoalLine[]
}

export const TRENDS_FILTER_PROPERTIES = new Set<keyof TrendsFilter>([
    'smoothingIntervals',
    'formula',
    'display',
    'showLegend',
    'breakdown_histogram_bin_count',
    'aggregationAxisFormat',
    'aggregationAxisPrefix',
    'aggregationAxisPostfix',
    'decimalPlaces',
    'showValuesOnSeries',
    'showLabelsOnSeries',
    'showPercentStackView',
    'yAxisScaleType',
    'hiddenLegendIndexes',
])

export interface TrendsQueryResponse extends AnalyticsQueryResponseBase<Record<string, any>[]> {
    /** Wether more breakdown values are available. */
    hasMore?: boolean
}

export type CachedTrendsQueryResponse = CachedQueryResponse<TrendsQueryResponse>

export type ResultCustomizationBase = {
    color: DataColorToken
}

export interface ResultCustomizationByPosition extends ResultCustomizationBase {
    assignmentBy: ResultCustomizationBy.Position
}

export interface ResultCustomizationByValue extends ResultCustomizationBase {
    assignmentBy: ResultCustomizationBy.Value
}

export type ResultCustomization = ResultCustomizationByValue | ResultCustomizationByPosition

export interface TrendsQuery extends InsightsQueryBase<TrendsQueryResponse> {
    kind: NodeKind.TrendsQuery
    /**
     * Granularity of the response. Can be one of `hour`, `day`, `week` or `month`
     *
     * @default day
     */
    interval?: IntervalType
    /** Events and actions to include */
    series: AnyEntityNode[]
    /** Properties specific to the trends insight */
    trendsFilter?: TrendsFilter
    /** Breakdown of the events and actions */
    breakdownFilter?: BreakdownFilter
    /** Compare to date range */
    compareFilter?: CompareFilter
    /**  Whether we should be comparing against a specific conversion goal */
    conversionGoal?: WebAnalyticsConversionGoal | null
}

export interface CompareFilter {
    /**
     * Whether to compare the current date range to a previous date range.
     * @default false
     */
    compare?: boolean

    /**
     * The date range to compare to. The value is a relative date. Examples of relative dates are: `-1y` for 1 year ago, `-14m` for 14 months ago, `-100w` for 100 weeks ago, `-14d` for 14 days ago, `-30h` for 30 hours ago.
     */
    compare_to?: string
}

/** `FunnelsFilterType` minus everything inherited from `FilterType` and persons modal related params */
export type FunnelsFilterLegacy = Omit<
    FunnelsFilterType,
    | keyof FilterType
    | 'funnel_step_breakdown'
    | 'funnel_correlation_person_entity'
    | 'funnel_correlation_person_converted'
    | 'entrance_period_start'
    | 'drop_off'
    | 'funnel_step'
    | 'funnel_custom_steps'
>

export interface FunnelExclusionSteps {
    funnelFromStep: integer
    funnelToStep: integer
}
export interface FunnelExclusionEventsNode extends EventsNode, FunnelExclusionSteps {}
export interface FunnelExclusionActionsNode extends ActionsNode, FunnelExclusionSteps {}
export type FunnelExclusion = FunnelExclusionEventsNode | FunnelExclusionActionsNode

export type FunnelsFilter = {
    /** @default [] */
    exclusions?: FunnelExclusion[]
    /** @default vertical */
    layout?: FunnelsFilterLegacy['layout']
    /** @asType integer */
    binCount?: FunnelsFilterLegacy['bin_count']
    /** @default first_touch */
    breakdownAttributionType?: FunnelsFilterLegacy['breakdown_attribution_type']
    breakdownAttributionValue?: integer
    funnelAggregateByHogQL?: FunnelsFilterLegacy['funnel_aggregate_by_hogql']
    funnelToStep?: integer
    funnelFromStep?: integer
    /** @default ordered */
    funnelOrderType?: FunnelsFilterLegacy['funnel_order_type']
    /** @default steps */
    funnelVizType?: FunnelsFilterLegacy['funnel_viz_type']
    /** @default 14 */
    funnelWindowInterval?: integer
    /** @default day */
    funnelWindowIntervalUnit?: FunnelsFilterLegacy['funnel_window_interval_unit']
    hiddenLegendBreakdowns?: string[]
    /** @default total */
    funnelStepReference?: FunnelsFilterLegacy['funnel_step_reference']
    useUdf?: boolean
    /** Customizations for the appearance of result datasets. */
    resultCustomizations?: Record<string, ResultCustomizationByValue>
}

export interface FunnelsQuery extends InsightsQueryBase<FunnelsQueryResponse> {
    kind: NodeKind.FunnelsQuery
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalType
    /** Events and actions to include */
    series: AnyEntityNode[]
    /** Properties specific to the funnels insight */
    funnelsFilter?: FunnelsFilter
    /** Breakdown of the events and actions */
    breakdownFilter?: BreakdownFilter
}

/** @asType integer */
type BinNumber = number
export type FunnelStepsResults = Record<string, any>[]
export type FunnelStepsBreakdownResults = Record<string, any>[][]
export type FunnelTimeToConvertResults = {
    average_conversion_time: number | null
    bins: [BinNumber, BinNumber][]
}
export type FunnelTrendsResults = Record<string, any>[]
export interface FunnelsQueryResponse
    extends AnalyticsQueryResponseBase<
        FunnelStepsResults | FunnelStepsBreakdownResults | FunnelTimeToConvertResults | FunnelTrendsResults
    > {
    isUdf?: boolean
}

export type CachedFunnelsQueryResponse = CachedQueryResponse<FunnelsQueryResponse>

/** `RetentionFilterType` minus everything inherited from `FilterType` */
export type RetentionFilterLegacy = Omit<RetentionFilterType, keyof FilterType>

export type RetentionFilter = {
    retentionType?: RetentionFilterLegacy['retention_type']
    retentionReference?: RetentionFilterLegacy['retention_reference']
    /** @default 11 */
    totalIntervals?: integer
    returningEntity?: RetentionFilterLegacy['returning_entity']
    targetEntity?: RetentionFilterLegacy['target_entity']
    /** @default Day */
    period?: RetentionFilterLegacy['period']
    showMean?: RetentionFilterLegacy['show_mean']
    cumulative?: RetentionFilterLegacy['cumulative']
}

export interface RetentionValue {
    count: integer
}

export interface RetentionResult {
    values: RetentionValue[]
    label: string
    /** @format date-time */
    date: string
}

export interface RetentionQueryResponse extends AnalyticsQueryResponseBase<RetentionResult[]> {}

export type CachedRetentionQueryResponse = CachedQueryResponse<RetentionQueryResponse>

export interface RetentionQuery extends InsightsQueryBase<RetentionQueryResponse> {
    kind: NodeKind.RetentionQuery
    /** Properties specific to the retention insight */
    retentionFilter: RetentionFilter
}

export interface PathsQueryResponse extends AnalyticsQueryResponseBase<Record<string, any>[]> {}

export type CachedPathsQueryResponse = CachedQueryResponse<PathsQueryResponse>

/** `PathsFilterType` minus everything inherited from `FilterType` and persons modal related params */
export type PathsFilterLegacy = Omit<
    PathsFilterType,
    keyof FilterType | 'path_start_key' | 'path_end_key' | 'path_dropoff_key'
>

export type PathsFilter = {
    /** @default 50 */
    edgeLimit?: integer
    pathsHogQLExpression?: PathsFilterLegacy['paths_hogql_expression']
    includeEventTypes?: PathsFilterLegacy['include_event_types']
    startPoint?: PathsFilterLegacy['start_point']
    endPoint?: PathsFilterLegacy['end_point']
    pathGroupings?: PathsFilterLegacy['path_groupings']
    excludeEvents?: PathsFilterLegacy['exclude_events']
    /** @default 5 */
    stepLimit?: integer
    pathReplacements?: PathsFilterLegacy['path_replacements']
    localPathCleaningFilters?: PathsFilterLegacy['local_path_cleaning_filters'] | null
    minEdgeWeight?: PathsFilterLegacy['min_edge_weight']
    maxEdgeWeight?: PathsFilterLegacy['max_edge_weight']

    /** Relevant only within actors query */
    pathStartKey?: string
    /** Relevant only within actors query */
    pathEndKey?: string
    /** Relevant only within actors query */
    pathDropoffKey?: string
}

export type FunnelPathsFilter = {
    funnelPathType: PathsFilterLegacy['funnel_paths']
    funnelSource: FunnelsQuery
    funnelStep?: integer
}

export interface PathsQuery extends InsightsQueryBase<PathsQueryResponse> {
    kind: NodeKind.PathsQuery
    /** Properties specific to the paths insight */
    pathsFilter: PathsFilter
    /** Used for displaying paths in relation to funnel steps. */
    funnelPathsFilter?: FunnelPathsFilter
}

/** `StickinessFilterType` minus everything inherited from `FilterType` and persons modal related params  */
export type StickinessFilterLegacy = Omit<StickinessFilterType, keyof FilterType | 'stickiness_days' | 'shown_as'>

export type StickinessOperator =
    | PropertyOperator.GreaterThanOrEqual
    | PropertyOperator.LessThanOrEqual
    | PropertyOperator.Exact

export type StickinessFilter = {
    display?: StickinessFilterLegacy['display']
    showLegend?: StickinessFilterLegacy['show_legend']
    showValuesOnSeries?: StickinessFilterLegacy['show_values_on_series']
    hiddenLegendIndexes?: integer[]
    stickinessCriteria?: {
        operator: StickinessOperator
        value: integer
    }
}

export const STICKINESS_FILTER_PROPERTIES = new Set<keyof StickinessFilter>([
    'display',
    'showLegend',
    'showValuesOnSeries',
    'hiddenLegendIndexes',
])

export interface StickinessQueryResponse extends AnalyticsQueryResponseBase<Record<string, any>[]> {}

export type CachedStickinessQueryResponse = CachedQueryResponse<StickinessQueryResponse>

export interface StickinessQuery
    extends Omit<InsightsQueryBase<StickinessQueryResponse>, 'aggregation_group_type_index'> {
    kind: NodeKind.StickinessQuery
    /**
     * Granularity of the response. Can be one of `hour`, `day`, `week` or `month`
     * @default day
     */
    interval?: IntervalType
    /**
     * How many intervals comprise a period. Only used for cohorts, otherwise default 1.
     */
    intervalCount?: integer
    /** Events and actions to include */
    series: AnyEntityNode[]
    /** Properties specific to the stickiness insight */
    stickinessFilter?: StickinessFilter
    /** Compare to date range */
    compareFilter?: CompareFilter
}

/** `LifecycleFilterType` minus everything inherited from `FilterType` */
export type LifecycleFilterLegacy = Omit<LifecycleFilterType, keyof FilterType | 'shown_as'> & {
    /** Lifecycles that have been removed from display are not included in this array */
    toggledLifecycles?: LifecycleToggle[]
} // using everything except what it inherits from FilterType

export type LifecycleFilter = {
    showValuesOnSeries?: LifecycleFilterLegacy['show_values_on_series']
    toggledLifecycles?: LifecycleFilterLegacy['toggledLifecycles']
    /** @default false */
    showLegend?: LifecycleFilterLegacy['show_legend']
}

export type RefreshType =
    | boolean
    | 'async'
    | 'async_except_on_cache_miss'
    | 'blocking'
    | 'force_async'
    | 'force_blocking'
    | 'force_cache'
    | 'lazy_async'

export interface QueryRequest {
    /** Client provided query ID. Can be used to retrieve the status or cancel the query. */
    client_query_id?: string
    // Sync the `refresh` description here with the two instances in posthog/api/insight.py
    /**
     * Whether results should be calculated sync or async, and how much to rely on the cache:
     * - `'blocking'` - calculate synchronously (returning only when the query is done), UNLESS there are very fresh results in the cache
     * - `'async'` - kick off background calculation (returning immediately with a query status), UNLESS there are very fresh results in the cache
     * - `'lazy_async'` - kick off background calculation, UNLESS there are somewhat fresh results in the cache
     * - `'force_blocking'` - calculate synchronously, even if fresh results are already cached
     * - `'force_async'` - kick off background calculation, even if fresh results are already cached
     * - `'force_cache'` - return cached data or a cache miss; always completes immediately as it never calculates
     * Background calculation can be tracked using the `query_status` response field.
     * @default 'blocking'
     */
    refresh?: RefreshType
    /** @deprecated Use `refresh` instead. */
    async?: boolean
    /**
     * Submit a JSON string representing a query for PostHog data analysis,
     * for example a HogQL query.
     *
     * Example payload:
     *
     * ```
     *
     * {"query": {"kind": "HogQLQuery", "query": "select * from events limit 100"}}
     *
     * ```
     *
     * For more details on HogQL queries,
     * see the [PostHog HogQL documentation](/docs/hogql#api-access).
     */
    query: QuerySchema
    filters_override?: DashboardFilter
    variables_override?: Record<string, Record<string, any>>
}

/**
 * All analytics query responses must inherit from this.
 * @internal - no need to emit to schema.json.
 */
export interface AnalyticsQueryResponseBase<T> {
    results: T
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTiming[]
    /** Generated HogQL query. */
    hogql?: string
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiers
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatus
}

interface CachedQueryResponseMixin {
    is_cached: boolean
    /**  @format date-time */
    last_refresh: string
    /**  @format date-time */
    next_allowed_client_refresh: string
    /**  @format date-time */
    cache_target_age?: string
    cache_key: string
    timezone: string
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatus
    /** What triggered the calculation of the query, leave empty if user/immediate */
    calculation_trigger?: string
}

type CachedQueryResponse<T> = T & CachedQueryResponseMixin

export type GenericCachedQueryResponse = CachedQueryResponse<Record<string, any>>

export interface QueryStatusResponse {
    query_status: QueryStatus
}

/** @deprecated Only exported for use in test_query_runner.py! Don't use anywhere else. */
export interface TestBasicQueryResponse extends AnalyticsQueryResponseBase<any[]> {}
/** @deprecated Only exported for use in test_query_runner.py! Don't use anywhere else. */
export type TestCachedBasicQueryResponse = CachedQueryResponse<TestBasicQueryResponse>

export interface CacheMissResponse {
    cache_key: string | null
    query_status?: QueryStatus
}

export type ClickhouseQueryProgress = {
    bytes_read: integer
    rows_read: integer
    estimated_rows_total: integer
    time_elapsed: integer
    active_cpu_time: integer
}

export type QueryStatus = {
    id: string
    /**
     * ONLY async queries use QueryStatus.
     * @default true
     */
    query_async: true
    team_id: integer
    insight_id?: integer
    dashboard_id?: integer
    /**
     * If the query failed, this will be set to true.
     * More information can be found in the error_message field.
     * @default false
     */
    error: boolean
    /**
     * Whether the query is still running. Will be true if the query is complete, even if it errored.
     * Either result or error will be set.
     * @default false
     */
    complete: boolean
    /**  @default null */
    error_message: string | null
    results?: any
    /**
     * When was the query execution task picked up by a worker.
     * @format date-time
     */
    pickup_time?: string
    /**
     * When was query execution task enqueued.
     * @format date-time
     */
    start_time?: string
    /**
     * When did the query execution task finish (whether successfully or not).
     * @format date-time
     */
    end_time?: string
    /**  @format date-time */
    expiration_time?: string
    task_id?: string
    query_progress?: ClickhouseQueryProgress
    labels?: string[]
}

export interface LifecycleQueryResponse extends AnalyticsQueryResponseBase<Record<string, any>[]> {}

export type CachedLifecycleQueryResponse = CachedQueryResponse<LifecycleQueryResponse>

export interface LifecycleQuery extends InsightsQueryBase<LifecycleQueryResponse> {
    kind: NodeKind.LifecycleQuery
    /**
     * Granularity of the response. Can be one of `hour`, `day`, `week` or `month`
     * @default day
     */
    interval?: IntervalType
    /** Events and actions to include */
    series: AnyEntityNode[]
    /** Properties specific to the lifecycle insight */
    lifecycleFilter?: LifecycleFilter
}

export interface ActorsQueryResponse extends AnalyticsQueryResponseBase<any[][]> {
    columns: any[]
    types: string[]
    hogql: string
    hasMore?: boolean
    limit: integer
    offset: integer
    missing_actors_count?: integer
}

export type CachedActorsQueryResponse = CachedQueryResponse<ActorsQueryResponse>

export interface ActorsQuery extends DataNode<ActorsQueryResponse> {
    kind: NodeKind.ActorsQuery
    source?: InsightActorsQuery | FunnelsActorsQuery | FunnelCorrelationActorsQuery | StickinessActorsQuery | HogQLQuery
    select?: HogQLExpression[]
    search?: string
    /** Currently only person filters supported. No filters for querying groups. See `filter_conditions()` in actor_strategies.py. */
    properties?: AnyPersonScopeFilter[] | PropertyGroupFilterValue
    /** Currently only person filters supported. No filters for querying groups. See `filter_conditions()` in actor_strategies.py. */
    fixedProperties?: AnyPersonScopeFilter[]
    orderBy?: string[]
    limit?: integer
    offset?: integer
}

export interface TimelineEntry {
    /** Session ID. None means out-of-session events */
    sessionId?: string
    events: EventType[]
    /** Duration of the recording in seconds. */
    recording_duration_s?: number
}

export interface SessionsTimelineQueryResponse extends AnalyticsQueryResponseBase<TimelineEntry[]> {
    hasMore?: boolean
}

export type CachedSessionsTimelineQueryResponse = CachedQueryResponse<SessionsTimelineQueryResponse>

export interface SessionsTimelineQuery extends DataNode<SessionsTimelineQueryResponse> {
    kind: NodeKind.SessionsTimelineQuery
    /** Fetch sessions only for a given person */
    personId?: string
    /** Only fetch sessions that started after this timestamp (default: '-24h') */
    after?: string
    /** Only fetch sessions that started before this timestamp (default: '+5s') */
    before?: string
}
export type WebAnalyticsPropertyFilter = EventPropertyFilter | PersonPropertyFilter | SessionPropertyFilter
export type WebAnalyticsPropertyFilters = WebAnalyticsPropertyFilter[]
export type ActionConversionGoal = {
    actionId: integer
}
export type CustomEventConversionGoal = {
    customEventName: string
}
export type WebAnalyticsConversionGoal = ActionConversionGoal | CustomEventConversionGoal
interface WebAnalyticsQueryBase<R extends Record<string, any>> extends DataNode<R> {
    dateRange?: DateRange
    properties: WebAnalyticsPropertyFilters
    conversionGoal?: WebAnalyticsConversionGoal | null
    compareFilter?: CompareFilter
    doPathCleaning?: boolean
    sampling?: {
        enabled?: boolean
        forceSamplingRate?: SamplingRate
    }
    filterTestAccounts?: boolean
    includeRevenue?: boolean
    /** @deprecated ignored, always treated as enabled **/
    useSessionsTable?: boolean
}

export interface WebOverviewQuery extends WebAnalyticsQueryBase<WebOverviewQueryResponse> {
    kind: NodeKind.WebOverviewQuery
}

export type WebOverviewItemKind = 'unit' | 'duration_s' | 'percentage' | 'currency'
export interface WebOverviewItem {
    key: string
    value?: number
    previous?: number
    kind: WebOverviewItemKind
    changeFromPreviousPct?: number
    isIncreaseBad?: boolean
}

export interface SamplingRate {
    numerator: number
    denominator?: number
}

export interface WebOverviewQueryResponse extends AnalyticsQueryResponseBase<WebOverviewItem[]> {
    samplingRate?: SamplingRate
    dateFrom?: string
    dateTo?: string
}

export type CachedWebOverviewQueryResponse = CachedQueryResponse<WebOverviewQueryResponse>

export enum WebStatsBreakdown {
    Page = 'Page',
    InitialPage = 'InitialPage',
    ExitPage = 'ExitPage', // not supported in the legacy version
    ExitClick = 'ExitClick',
    ScreenName = 'ScreenName',
    InitialChannelType = 'InitialChannelType',
    InitialReferringDomain = 'InitialReferringDomain',
    InitialUTMSource = 'InitialUTMSource',
    InitialUTMCampaign = 'InitialUTMCampaign',
    InitialUTMMedium = 'InitialUTMMedium',
    InitialUTMTerm = 'InitialUTMTerm',
    InitialUTMContent = 'InitialUTMContent',
    InitialUTMSourceMediumCampaign = 'InitialUTMSourceMediumCampaign',
    Browser = 'Browser',
    OS = 'OS',
    Viewport = 'Viewport',
    DeviceType = 'DeviceType',
    Country = 'Country',
    Region = 'Region',
    City = 'City',
    Timezone = 'Timezone',
    Language = 'Language',
}
export interface WebStatsTableQuery extends WebAnalyticsQueryBase<WebStatsTableQueryResponse> {
    kind: NodeKind.WebStatsTableQuery
    breakdownBy: WebStatsBreakdown
    includeScrollDepth?: boolean // automatically sets includeBounceRate to true
    includeBounceRate?: boolean
    limit?: integer
}
export interface WebStatsTableQueryResponse extends AnalyticsQueryResponseBase<unknown[]> {
    types?: unknown[]
    columns?: unknown[]
    hogql?: string
    samplingRate?: SamplingRate
    hasMore?: boolean
    limit?: integer
    offset?: integer
}
export type CachedWebStatsTableQueryResponse = CachedQueryResponse<WebStatsTableQueryResponse>

export interface WebExternalClicksTableQuery extends WebAnalyticsQueryBase<WebExternalClicksTableQueryResponse> {
    kind: NodeKind.WebExternalClicksTableQuery
    limit?: integer
    stripQueryParams?: boolean
}
export interface WebExternalClicksTableQueryResponse extends AnalyticsQueryResponseBase<unknown[]> {
    types?: unknown[]
    columns?: unknown[]
    hogql?: string
    samplingRate?: SamplingRate
    hasMore?: boolean
    limit?: integer
    offset?: integer
}
export type CachedWebExternalClicksTableQueryResponse = CachedQueryResponse<WebExternalClicksTableQueryResponse>

export interface WebGoalsQuery extends WebAnalyticsQueryBase<WebGoalsQueryResponse> {
    kind: NodeKind.WebGoalsQuery
    limit?: integer
}

export interface WebGoalsQueryResponse extends AnalyticsQueryResponseBase<unknown[]> {
    types?: unknown[]
    columns?: unknown[]
    hogql?: string
    samplingRate?: SamplingRate
    hasMore?: boolean
    limit?: integer
    offset?: integer
}
export type CachedWebGoalsQueryResponse = CachedQueryResponse<WebGoalsQueryResponse>

export type WebVitalsMetric = 'INP' | 'LCP' | 'CLS' | 'FCP'
export type WebVitalsPercentile = PropertyMathType.P75 | PropertyMathType.P90 | PropertyMathType.P99
export type WebVitalsMetricBand = 'good' | 'needs_improvements' | 'poor'

export interface WebVitalsQuery<T = InsightQueryNode> extends WebAnalyticsQueryBase<WebGoalsQueryResponse> {
    kind: NodeKind.WebVitalsQuery
    source: T
}

export interface WebVitalsItemAction {
    custom_name: WebVitalsMetric
    math: WebVitalsPercentile
}
export interface WebVitalsItem {
    data: number[]
    days: string[]
    action: WebVitalsItemAction
}

export type WebVitalsQueryResponse = AnalyticsQueryResponseBase<WebVitalsItem[]>
export type CachedWebVitalsQueryResponse = CachedQueryResponse<WebVitalsQueryResponse>

export interface WebVitalsPathBreakdownQuery extends WebAnalyticsQueryBase<WebVitalsPathBreakdownQueryResponse> {
    kind: NodeKind.WebVitalsPathBreakdownQuery
    percentile: WebVitalsPercentile
    metric: WebVitalsMetric

    // Threshold for this specific metric, these are stored in the frontend only
    // so let's send them back to the backend to be used in the query
    // This tuple represents a [good, poor] threshold, where values below good are good and values above poor are poor
    // Values in between the two values are the threshold for needs_improvements
    thresholds: [number, number]
}

export type WebVitalsPathBreakdownResultItem = { path: string; value: number }
export type WebVitalsPathBreakdownResult = Record<WebVitalsMetricBand, WebVitalsPathBreakdownResultItem[]>

// NOTE: The response is an array of results because pydantic requires it, but this will always have a single entry
// hence the tuple type rather than a single object.
export type WebVitalsPathBreakdownQueryResponse = AnalyticsQueryResponseBase<[WebVitalsPathBreakdownResult]>
export type CachedWebVitalsPathBreakdownQueryResponse = CachedQueryResponse<WebVitalsPathBreakdownQueryResponse>

export enum SessionAttributionGroupBy {
    ChannelType = 'ChannelType',
    Medium = 'Medium',
    Source = 'Source',
    Campaign = 'Campaign',
    AdIds = 'AdIds',
    ReferringDomain = 'ReferringDomain',
    InitialURL = 'InitialURL',
}
export interface SessionAttributionExplorerQuery extends DataNode<SessionAttributionExplorerQueryResponse> {
    kind: NodeKind.SessionAttributionExplorerQuery
    groupBy: SessionAttributionGroupBy[]
    filters?: {
        properties?: SessionPropertyFilter[]
        dateRange?: DateRange
    }
    limit?: integer
    offset?: integer
}

export interface SessionAttributionExplorerQueryResponse extends AnalyticsQueryResponseBase<unknown> {
    hasMore?: boolean
    limit?: integer
    offset?: integer
    types?: unknown[]
    columns?: unknown[]
}
export type CachedSessionAttributionExplorerQueryResponse = CachedQueryResponse<SessionAttributionExplorerQueryResponse>

export interface ErrorTrackingQuery extends DataNode<ErrorTrackingQueryResponse> {
    kind: NodeKind.ErrorTrackingQuery
    issueId?: ErrorTrackingIssue['id']
    orderBy?: 'last_seen' | 'first_seen' | 'occurrences' | 'users' | 'sessions'
    dateRange: DateRange
    assignee?: ErrorTrackingIssueAssignee | null
    filterGroup?: PropertyGroupFilter
    filterTestAccounts?: boolean
    searchQuery?: string
    customVolume?: ErrorTrackingSparklineConfig | null
    limit?: integer
    offset?: integer
}

export interface ErrorTrackingIssueAssignee {
    type: 'user_group' | 'user'
    id: integer | string
}

export type ErrorTrackingSparklineConfig = {
    value: integer
    interval: 'minute' | 'hour' | 'day' | 'week' | 'month'
}

export interface ErrorTrackingIssue {
    id: string
    name: string | null
    description: string | null
    /**  @format date-time */
    first_seen: string
    /**  @format date-time */
    last_seen: string
    earliest?: string
    occurrences: number
    sessions: number
    users: number
    volumeDay: number[]
    volumeMonth: number[]
    customVolume?: number[]
    assignee: ErrorTrackingIssueAssignee | null
    status: 'archived' | 'active' | 'resolved' | 'pending_release'
}

export interface ErrorTrackingQueryResponse extends AnalyticsQueryResponseBase<ErrorTrackingIssue[]> {
    hasMore?: boolean
    limit?: integer
    offset?: integer
    columns?: string[]
}
export type CachedErrorTrackingQueryResponse = CachedQueryResponse<ErrorTrackingQueryResponse>

export type InsightQueryNode =
    | TrendsQuery
    | FunnelsQuery
    | RetentionQuery
    | PathsQuery
    | StickinessQuery
    | LifecycleQuery

export interface ExperimentVariantTrendsBaseStats {
    key: string
    count: number
    exposure: number
    absolute_exposure: number
}

export interface ExperimentVariantFunnelsBaseStats {
    key: string
    success_count: number
    failure_count: number
}

export enum ExperimentSignificanceCode {
    Significant = 'significant',
    NotEnoughExposure = 'not_enough_exposure',
    LowWinProbability = 'low_win_probability',
    HighLoss = 'high_loss',
    HighPValue = 'high_p_value',
}

export interface ExperimentTrendsQueryResponse {
    kind: NodeKind.ExperimentTrendsQuery
    insight: Record<string, any>[]
    count_query?: TrendsQuery
    exposure_query?: TrendsQuery
    variants: ExperimentVariantTrendsBaseStats[]
    probability: Record<string, number>
    significant: boolean
    significance_code: ExperimentSignificanceCode
    stats_version?: integer
    p_value: number
    credible_intervals: Record<string, [number, number]>
}

export type CachedExperimentTrendsQueryResponse = CachedQueryResponse<ExperimentTrendsQueryResponse>

export interface ExperimentFunnelsQueryResponse {
    kind: NodeKind.ExperimentFunnelsQuery
    insight: Record<string, any>[][]
    funnels_query?: FunnelsQuery
    variants: ExperimentVariantFunnelsBaseStats[]
    probability: Record<string, number>
    significant: boolean
    significance_code: ExperimentSignificanceCode
    expected_loss: number
    credible_intervals: Record<string, [number, number]>
    stats_version?: integer
}

export type CachedExperimentFunnelsQueryResponse = CachedQueryResponse<ExperimentFunnelsQueryResponse>

export interface ExperimentFunnelsQuery extends DataNode<ExperimentFunnelsQueryResponse> {
    kind: NodeKind.ExperimentFunnelsQuery
    name?: string
    experiment_id?: integer
    funnels_query: FunnelsQuery
}

export interface ExperimentTrendsQuery extends DataNode<ExperimentTrendsQueryResponse> {
    kind: NodeKind.ExperimentTrendsQuery
    name?: string
    experiment_id?: integer
    count_query: TrendsQuery
    // Defaults to $feature_flag_called if not specified
    // https://github.com/PostHog/posthog/blob/master/posthog/hogql_queries/experiments/experiment_trends_query_runner.py
    exposure_query?: TrendsQuery
}

/**
 * @discriminator kind
 */
export type InsightQuerySource = InsightQueryNode
export type InsightNodeKind = InsightQueryNode['kind']
export type InsightFilterProperty =
    | 'trendsFilter'
    | 'funnelsFilter'
    | 'retentionFilter'
    | 'pathsFilter'
    | 'stickinessFilter'
    | 'lifecycleFilter'
export type InsightFilter =
    | TrendsFilter
    | FunnelsFilter
    | RetentionFilter
    | PathsFilter
    | StickinessFilter
    | LifecycleFilter

export type Day = integer

export interface InsightActorsQueryBase extends DataNode<ActorsQueryResponse> {
    includeRecordings?: boolean
    modifiers?: HogQLQueryModifiers
}

export interface InsightActorsQuery<S extends InsightsQueryBase<AnalyticsQueryResponseBase<any>> = InsightQuerySource>
    extends InsightActorsQueryBase {
    kind: NodeKind.InsightActorsQuery
    source: S
    day?: string | Day
    status?: string
    /** An interval selected out of available intervals in source query. */
    interval?: integer
    series?: integer
    breakdown?: string | BreakdownValueInt | string[]
    compare?: 'current' | 'previous'
}

export interface StickinessActorsQuery extends InsightActorsQuery {
    operator?: StickinessOperator
}

export interface FunnelsActorsQuery extends InsightActorsQueryBase {
    kind: NodeKind.FunnelsActorsQuery
    source: FunnelsQuery
    /** Index of the step for which we want to get the timestamp for, per person.
     * Positive for converted persons, negative for dropped of persons. */
    funnelStep?: integer
    /** Custom step numbers to get persons for. This overrides `funnelStep`. Primarily for correlation use. */
    funnelCustomSteps?: integer[]
    /** The breakdown value for which to get persons for. This is an array for
     * person and event properties, a string for groups and an integer for cohorts. */
    funnelStepBreakdown?: BreakdownKeyType
    funnelTrendsDropOff?: boolean
    /** Used together with `funnelTrendsDropOff` for funnels time conversion date for the persons modal. */
    funnelTrendsEntrancePeriodStart?: string
}

export interface FunnelCorrelationActorsQuery extends InsightActorsQueryBase {
    kind: NodeKind.FunnelCorrelationActorsQuery
    source: FunnelCorrelationQuery
    funnelCorrelationPersonConverted?: boolean
    funnelCorrelationPersonEntity?: AnyEntityNode
    funnelCorrelationPropertyValues?: AnyPropertyFilter[]
}

export interface EventDefinition {
    event: string
    properties: Record<string, any>
    elements: any[]
}

export interface EventOddsRatioSerialized {
    event: EventDefinition
    success_count: integer
    failure_count: integer
    odds_ratio: number
    correlation_type: 'success' | 'failure'
}

export interface FunnelCorrelationResult {
    events: EventOddsRatioSerialized[]
    skewed: boolean
}

export interface FunnelCorrelationResponse extends AnalyticsQueryResponseBase<FunnelCorrelationResult> {
    columns?: any[]
    types?: any[]
    hasMore?: boolean
    limit?: integer
    offset?: integer
}
export type CachedFunnelCorrelationResponse = FunnelCorrelationResponse & CachedRetentionQueryResponse

export enum FunnelCorrelationResultsType {
    Events = 'events',
    Properties = 'properties',
    EventWithProperties = 'event_with_properties',
}

export interface FunnelCorrelationQuery extends Node<FunnelCorrelationResponse> {
    kind: NodeKind.FunnelCorrelationQuery
    source: FunnelsActorsQuery
    funnelCorrelationType: FunnelCorrelationResultsType

    /* Events */
    funnelCorrelationExcludeEventNames?: string[]

    /* Events with properties */
    funnelCorrelationEventNames?: string[]
    funnelCorrelationEventExcludePropertyNames?: string[]

    /* Properties */
    funnelCorrelationNames?: string[]
    funnelCorrelationExcludeNames?: string[]
}

/**  @format date-time */
export type DatetimeDay = string

export type BreakdownValueInt = integer
export interface BreakdownItem {
    label: string
    value: string | BreakdownValueInt
}
export interface MultipleBreakdownOptions {
    values: BreakdownItem[]
}

export interface InsightActorsQueryOptionsResponse {
    // eslint-disable-next-line @typescript-eslint/no-duplicate-type-constituents
    day?: { label: string; value: string | DatetimeDay | Day }[]
    status?: { label: string; value: string }[]
    interval?: {
        label: string
        /**
         * An interval selected out of available intervals in source query

         */
        value: integer
    }[]
    breakdown?: BreakdownItem[]
    breakdowns?: MultipleBreakdownOptions[]
    series?: {
        label: string
        value: integer
    }[]
    compare?: {
        label: string
        value: string
    }[]
}
export const insightActorsQueryOptionsResponseKeys: string[] = [
    'day',
    'status',
    'interval',
    'breakdown',
    'breakdowns',
    'series',
    'compare',
]

export type CachedInsightActorsQueryOptionsResponse = CachedQueryResponse<InsightActorsQueryOptionsResponse>

export interface InsightActorsQueryOptions extends Node<InsightActorsQueryOptionsResponse> {
    kind: NodeKind.InsightActorsQueryOptions
    source: InsightActorsQuery | FunnelsActorsQuery | FunnelCorrelationActorsQuery | StickinessActorsQuery
}

export interface DatabaseSchemaSchema {
    id: string
    name: string
    should_sync: boolean
    incremental: boolean
    status?: string
    last_synced_at?: string
}

export interface DatabaseSchemaSource {
    id: string
    status: string
    source_type: string
    prefix: string
    last_synced_at?: string
}

export interface DatabaseSchemaField {
    name: string
    hogql_value: string
    type: DatabaseSerializedFieldType
    schema_valid: boolean
    table?: string
    fields?: string[]
    chain?: (string | integer)[]
    id?: string
}

export interface DatabaseSchemaTableCommon {
    type: 'posthog' | 'data_warehouse' | 'view' | 'batch_export' | 'materialized_view'
    id: string
    name: string
    fields: Record<string, DatabaseSchemaField>
}

export interface DatabaseSchemaViewTable extends DatabaseSchemaTableCommon {
    type: 'view'
    query: HogQLQuery
}

export interface DatabaseSchemaMaterializedViewTable extends DatabaseSchemaTableCommon {
    type: 'materialized_view'
    query: HogQLQuery
    last_run_at?: string
    status?: string
}

export interface DatabaseSchemaPostHogTable extends DatabaseSchemaTableCommon {
    type: 'posthog'
}

export interface DatabaseSchemaDataWarehouseTable extends DatabaseSchemaTableCommon {
    type: 'data_warehouse'
    format: string
    url_pattern: string
    schema?: DatabaseSchemaSchema
    source?: DatabaseSchemaSource
}

export interface DatabaseSchemaBatchExportTable extends DatabaseSchemaTableCommon {
    type: 'batch_export'
}

export type DatabaseSchemaTable =
    | DatabaseSchemaPostHogTable
    | DatabaseSchemaDataWarehouseTable
    | DatabaseSchemaViewTable
    | DatabaseSchemaBatchExportTable
    | DatabaseSchemaMaterializedViewTable

export interface DatabaseSchemaQueryResponse {
    tables: Record<string, DatabaseSchemaTable>
}

export interface DatabaseSchemaQuery extends DataNode<DatabaseSchemaQueryResponse> {
    kind: NodeKind.DatabaseSchemaQuery
}

export type DatabaseSerializedFieldType =
    | 'integer'
    | 'float'
    | 'string'
    | 'datetime'
    | 'date'
    | 'boolean'
    | 'array'
    | 'json'
    | 'lazy_table'
    | 'virtual_table'
    | 'field_traverser'
    | 'expression'
    | 'view'
    | 'materialized_view'

export type HogQLExpression = string

// Various utility types below

export interface DateRange {
    date_from?: string | null
    date_to?: string | null
    /** Whether the date_from and date_to should be used verbatim. Disables
     * rounding to the start and end of period.
     * @default false
     * */
    explicitDate?: boolean | null
}

export type MultipleBreakdownType = Extract<BreakdownType, 'person' | 'event' | 'group' | 'session' | 'hogql'>

export interface Breakdown {
    type?: MultipleBreakdownType | null
    property: string
    normalize_url?: boolean
    group_type_index?: integer | null
    histogram_bin_count?: integer // trends breakdown histogram bin
}

export interface BreakdownFilter {
    // TODO: unclutter
    /** @default event */
    breakdown_type?: BreakdownType | null
    breakdown_limit?: integer
    breakdown?: string | integer | (string | integer)[] | null
    breakdown_normalize_url?: boolean
    /**
     * @maxLength 3
     */
    breakdowns?: Breakdown[] // We want to limit maximum count of breakdowns avoiding overloading.
    breakdown_group_type_index?: integer | null
    breakdown_histogram_bin_count?: integer // trends breakdown histogram bin
    breakdown_hide_other_aggregation?: boolean | null // hides the "other" field for trends
}

// TODO: Rename to `DashboardFilters` for consistency with `HogQLFilters`
export interface DashboardFilter {
    date_from?: string | null
    date_to?: string | null
    properties?: AnyPropertyFilter[] | null
    breakdown_filter?: BreakdownFilter | null
}

export interface InsightsThresholdBounds {
    lower?: number
    upper?: number
}

export enum InsightThresholdType {
    ABSOLUTE = 'absolute',
    PERCENTAGE = 'percentage',
}

export interface InsightThreshold {
    type: InsightThresholdType
    bounds?: InsightsThresholdBounds
}

export enum AlertConditionType {
    ABSOLUTE_VALUE = 'absolute_value', // default alert, checks absolute value of current interval
    RELATIVE_INCREASE = 'relative_increase', // checks increase in value during current interval compared to previous interval
    RELATIVE_DECREASE = 'relative_decrease', // checks decrease in value during current interval compared to previous interval
}

export interface AlertCondition {
    // Conditions in addition to the separate threshold
    // TODO: Think about things like relative thresholds, rate of change, etc.
    type: AlertConditionType
}

export enum AlertState {
    FIRING = 'Firing',
    NOT_FIRING = 'Not firing',
    ERRORED = 'Errored',
    SNOOZED = 'Snoozed',
}

export enum AlertCalculationInterval {
    HOURLY = 'hourly',
    DAILY = 'daily',
    WEEKLY = 'weekly',
    MONTHLY = 'monthly',
}

export interface TrendsAlertConfig {
    type: 'TrendsAlertConfig'
    series_index: integer
    check_ongoing_interval?: boolean
}

export interface HogCompileResponse {
    bytecode: any[]
    locals: any[]
}

export interface SuggestedQuestionsQuery extends DataNode<SuggestedQuestionsQueryResponse> {
    kind: NodeKind.SuggestedQuestionsQuery
}

export interface SuggestedQuestionsQueryResponse {
    questions: string[]
}

export type CachedSuggestedQuestionsQueryResponse = CachedQueryResponse<SuggestedQuestionsQueryResponse>

export interface TeamTaxonomyItem {
    event: string
    count: integer
}

export type TeamTaxonomyResponse = TeamTaxonomyItem[]

export interface TeamTaxonomyQuery extends DataNode<TeamTaxonomyQueryResponse> {
    kind: NodeKind.TeamTaxonomyQuery
}

export type TeamTaxonomyQueryResponse = AnalyticsQueryResponseBase<TeamTaxonomyResponse>

export type CachedTeamTaxonomyQueryResponse = CachedQueryResponse<TeamTaxonomyQueryResponse>

export interface EventTaxonomyItem {
    property: string
    sample_values: string[]
    sample_count: integer
}

export type EventTaxonomyResponse = EventTaxonomyItem[]

export interface EventTaxonomyQuery extends DataNode<EventTaxonomyQueryResponse> {
    kind: NodeKind.EventTaxonomyQuery
    event: string
    properties?: string[]
    maxPropertyValues?: integer
}

export type EventTaxonomyQueryResponse = AnalyticsQueryResponseBase<EventTaxonomyResponse>

export type CachedEventTaxonomyQueryResponse = CachedQueryResponse<EventTaxonomyQueryResponse>

export interface ActorsPropertyTaxonomyResponse {
    // Values can be floats and integers. The comment below is to preserve the `integer` type.
    // eslint-disable-next-line @typescript-eslint/no-duplicate-type-constituents
    sample_values: (string | number | boolean | integer)[]
    sample_count: integer
}

export interface ActorsPropertyTaxonomyQuery extends DataNode<ActorsPropertyTaxonomyQueryResponse> {
    kind: NodeKind.ActorsPropertyTaxonomyQuery
    property: string
    group_type_index?: integer
    maxPropertyValues?: integer
}

export type ActorsPropertyTaxonomyQueryResponse = AnalyticsQueryResponseBase<ActorsPropertyTaxonomyResponse>

export type CachedActorsPropertyTaxonomyQueryResponse = CachedQueryResponse<ActorsPropertyTaxonomyQueryResponse>

export enum CustomChannelField {
    UTMSource = 'utm_source',
    UTMMedium = 'utm_medium',
    UTMCampaign = 'utm_campaign',
    ReferringDomain = 'referring_domain',
    URL = 'url',
    Pathname = 'pathname',
    Hostname = 'hostname',
}

export enum CustomChannelOperator {
    Exact = 'exact',
    IsNot = 'is_not',
    IsSet = 'is_set',
    IsNotSet = 'is_not_set',
    IContains = 'icontains',
    NotIContains = 'not_icontains',
    Regex = 'regex',
    NotRegex = 'not_regex',
}

export interface CustomChannelCondition {
    key: CustomChannelField
    value?: string | string[]
    op: CustomChannelOperator
    id: string // the ID is only needed for the drag and drop, so only needs to be unique with one set of rules
}

export interface CustomChannelRule {
    items: CustomChannelCondition[]
    combiner: FilterLogicalOperator
    channel_type: string
    id: string // the ID is only needed for the drag and drop, so only needs to be unique with one set of rules
}

export enum DefaultChannelTypes {
    CrossNetwork = 'Cross Network',
    PaidSearch = 'Paid Search',
    PaidSocial = 'Paid Social',
    PaidVideo = 'Paid Video',
    PaidShopping = 'Paid Shopping',
    PaidUnknown = 'Paid Unknown',
    Direct = 'Direct',
    OrganicSearch = 'Organic Search',
    OrganicSocial = 'Organic Social',
    OrganicVideo = 'Organic Video',
    OrganicShopping = 'Organic Shopping',
    Push = 'Push',
    SMS = 'SMS',
    Audio = 'Audio',
    Email = 'Email',
    Referral = 'Referral',
    Affiliate = 'Affiliate',
    Unknown = 'Unknown',
}

export interface LLMTraceEvent {
    id: string
    event: string
    properties: Record<string, any>
    createdAt: string
}

// Snake-case here for the DataTable component.
export interface LLMTracePerson {
    uuid: string
    created_at: string
    properties: Record<string, any>
    distinct_id: string
}

export interface LLMTrace {
    id: string
    createdAt: string
    person: LLMTracePerson
    totalLatency?: number
    inputTokens?: number
    outputTokens?: number
    inputCost?: number
    outputCost?: number
    totalCost?: number
    inputState?: any
    outputState?: any
    traceName?: string
    events: LLMTraceEvent[]
}

export interface TracesQueryResponse extends AnalyticsQueryResponseBase<LLMTrace[]> {
    hasMore?: boolean
    limit?: integer
    offset?: integer
    columns?: string[]
}

export interface TracesQuery extends DataNode<TracesQueryResponse> {
    kind: NodeKind.TracesQuery
    traceId?: string
    dateRange?: DateRange
    limit?: integer
    offset?: integer
    filterTestAccounts?: boolean
    /** Properties configurable in the interface */
    properties?: AnyPropertyFilter[]
}

export type CachedTracesQueryResponse = CachedQueryResponse<TracesQueryResponse>

export interface RevenueTrackingEventItem {
    eventName: string
    revenueProperty: string
}

export interface RevenueTrackingConfig {
    events: RevenueTrackingEventItem[]
}
