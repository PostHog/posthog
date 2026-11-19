/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `student` - Student
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Student: 'student',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

export interface DashboardV2SummaryApi {
    /** Unique identifier of the dashboard row. API routes use `uid`. */
    id: string
    /** Identifier of the dashboard in URLs and in its spec. It is unique in the project. */
    uid: string
    /** Title from the spec. */
    title: string
    /**
     * Description from the spec, or null when the spec has none.
     * @nullable
     */
    description: string | null
    /** Folder titles from the spec, separated by `/`. Empty for the top level. */
    folder: string
    /** Tags from the spec. */
    tags: string[]
    /** Number of the latest saved version. It starts at 1, and each save adds 1. */
    version: number
    /** When the dashboard was created. */
    created_at: string
    /** User who created the dashboard, or null when unknown. */
    readonly created_by: UserBasicApi | null
    /** When the dashboard was last saved. */
    last_modified_at: string
    /** User who last saved the dashboard, or null when unknown. */
    readonly last_modified_by: UserBasicApi | null
}

export interface PaginatedDashboardV2SummaryListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DashboardV2SummaryApi[]
}

export type DashboardV2DashboardLinkApiType =
    | (typeof DashboardV2DashboardLinkApiType)[keyof typeof DashboardV2DashboardLinkApiType]
    | null

export const DashboardV2DashboardLinkApiType = {
    Link: 'link',
    Dashboards: 'dashboards',
} as const

export type DashboardV2DashboardLinkApiIcon =
    | (typeof DashboardV2DashboardLinkApiIcon)[keyof typeof DashboardV2DashboardLinkApiIcon]
    | null

export const DashboardV2DashboardLinkApiIcon = {
    External: 'external',
    Dashboard: 'dashboard',
    Doc: 'doc',
    Info: 'info',
    Bell: 'bell',
    Grafana: 'grafana',
    Github: 'github',
} as const

export interface DashboardV2DashboardLinkApi {
    title: string
    type?: DashboardV2DashboardLinkApiType
    url?: string | null
    tags?: string[] | null
    asDropdown?: boolean | null
    icon?: DashboardV2DashboardLinkApiIcon
    tooltip?: string | null
    newTab?: boolean | null
    keepTime?: boolean | null
    includeVars?: boolean | null
}

export type DashboardV2SpecApiLinkStyle =
    | (typeof DashboardV2SpecApiLinkStyle)[keyof typeof DashboardV2SpecApiLinkStyle]
    | null

export const DashboardV2SpecApiLinkStyle = {
    Buttons: 'buttons',
    Tabs: 'tabs',
} as const

export type DashboardV2SpecApiDisplay =
    | (typeof DashboardV2SpecApiDisplay)[keyof typeof DashboardV2SpecApiDisplay]
    | null

export const DashboardV2SpecApiDisplay = {
    Spacious: 'spacious',
    Dense: 'dense',
} as const

export interface DashboardV2TimeRangeApi {
    from: string
    to: string
}

export interface DashboardV2CustomVariableApi {
    /** @pattern ^[A-Za-z_][A-Za-z0-9_]*$ */
    name: string
    label?: string | null
    hidden?: boolean | null
    multi?: boolean | null
    includeAll?: boolean | null
    allValue?: string | null
    current?: string | string[] | null
    type: 'custom'
    options: string[]
}

export type DashboardV2QueryVariableLanguageEnumApi =
    (typeof DashboardV2QueryVariableLanguageEnumApi)[keyof typeof DashboardV2QueryVariableLanguageEnumApi]

export const DashboardV2QueryVariableLanguageEnumApi = {
    Promql: 'promql',
    Hogql: 'hogql',
    Sql: 'sql',
    Logql: 'logql',
    Insight: 'insight',
} as const

export interface DashboardV2QueryVariableApi {
    /** @pattern ^[A-Za-z_][A-Za-z0-9_]*$ */
    name: string
    label?: string | null
    hidden?: boolean | null
    multi?: boolean | null
    includeAll?: boolean | null
    allValue?: string | null
    current?: string | string[] | null
    type: 'query'
    language: DashboardV2QueryVariableLanguageEnumApi
    query: string
    regex?: string | null
}

export interface DashboardV2TextboxVariableApi {
    /** @pattern ^[A-Za-z_][A-Za-z0-9_]*$ */
    name: string
    label?: string | null
    hidden?: boolean | null
    multi?: boolean | null
    includeAll?: boolean | null
    allValue?: string | null
    current?: string | string[] | null
    type: 'textbox'
    default?: string | null
}

export interface DashboardV2IntervalVariableApi {
    /** @pattern ^[A-Za-z_][A-Za-z0-9_]*$ */
    name: string
    label?: string | null
    hidden?: boolean | null
    multi?: boolean | null
    includeAll?: boolean | null
    allValue?: string | null
    current?: string | string[] | null
    type: 'interval'
    options: string[]
}

export interface DashboardV2ConstantVariableApi {
    /** @pattern ^[A-Za-z_][A-Za-z0-9_]*$ */
    name: string
    label?: string | null
    hidden?: boolean | null
    multi?: boolean | null
    includeAll?: boolean | null
    allValue?: string | null
    current?: string | string[] | null
    type: 'constant'
    value: string
}

export interface DashboardV2AdhocVariableApi {
    /** @pattern ^[A-Za-z_][A-Za-z0-9_]*$ */
    name: string
    label?: string | null
    hidden?: boolean | null
    multi?: boolean | null
    includeAll?: boolean | null
    allValue?: string | null
    current?: string | string[] | null
    type: 'adhoc'
}

export interface DashboardV2PanelItemApi {
    panel: string
    /**
     * @minimum 0
     * @maximum 23
     */
    x: number
    /** @minimum 0 */
    y: number
    /**
     * @minimum 1
     * @maximum 24
     */
    w: number
    /** @minimum 1 */
    h: number
}

export interface DashboardV2RowItemApi {
    row: string
    /** @minimum 0 */
    y: number
    collapsed?: boolean | null
    repeat?: string | null
    items: DashboardV2PanelItemApi[]
}

export interface DashboardV2TabApi {
    title: string
    items: DashboardV2PanelItemApi[]
}

export interface DashboardV2TabsItemApi {
    tabs: string
    /** @minimum 0 */
    y: number
    items: DashboardV2TabApi[]
}

export interface DashboardV2LayoutApi {
    type: 'grid'
    columns?: 24
    items: (DashboardV2PanelItemApi | DashboardV2RowItemApi | DashboardV2TabsItemApi)[]
}

export type DashboardV2PanelApiDescriptionMode =
    | (typeof DashboardV2PanelApiDescriptionMode)[keyof typeof DashboardV2PanelApiDescriptionMode]
    | null

export const DashboardV2PanelApiDescriptionMode = {
    Info: 'info',
    Below: 'below',
    Hidden: 'hidden',
} as const

export type DashboardV2VizApiOptions = { [key: string]: unknown } | null

export interface DashboardV2VizApi {
    type: string
    options?: DashboardV2VizApiOptions
}

export type DashboardV2TargetLanguageEnumApi =
    (typeof DashboardV2TargetLanguageEnumApi)[keyof typeof DashboardV2TargetLanguageEnumApi]

export const DashboardV2TargetLanguageEnumApi = {
    Promql: 'promql',
    Hogql: 'hogql',
    Sql: 'sql',
    Logql: 'logql',
    Insight: 'insight',
} as const

export type DashboardV2TargetApiFormat =
    | (typeof DashboardV2TargetApiFormat)[keyof typeof DashboardV2TargetApiFormat]
    | null

export const DashboardV2TargetApiFormat = {
    TimeSeries: 'time_series',
    Table: 'table',
} as const

export type DashboardV2BuilderStateSourceEnumApi =
    (typeof DashboardV2BuilderStateSourceEnumApi)[keyof typeof DashboardV2BuilderStateSourceEnumApi]

export const DashboardV2BuilderStateSourceEnumApi = {
    Metrics: 'metrics',
    Logs: 'logs',
    Events: 'events',
    Traces: 'traces',
} as const

export interface DashboardV2BuilderStateApi {
    source: DashboardV2BuilderStateSourceEnumApi
    [key: string]: unknown
}

export interface DashboardV2TargetApi {
    refId: string
    language: DashboardV2TargetLanguageEnumApi
    query: string
    legend?: string | null
    bucketed?: boolean | null
    instant?: boolean | null
    format?: DashboardV2TargetApiFormat
    hide?: boolean | null
    builder?: DashboardV2BuilderStateApi | null
    builtBy?: string | null
}

export interface DashboardV2PartitionTransformApi {
    type: 'partition'
    by: string
}

export interface DashboardV2OrganizeTransformApi {
    type: 'organize'
    /** @minItems 1 */
    fields: string[]
}

export interface DashboardV2MergeTransformApi {
    type: 'merge'
    on: string
}

export interface DashboardV2LimitTransformApi {
    type: 'limit'
    /** @exclusiveMinimum 0 */
    n: number
}

export interface DashboardV2SortTransformApi {
    type: 'sort'
    field: string
    desc?: boolean | null
}

export interface DashboardV2RenameTransformApi {
    type: 'rename'
    from: string
    to: string
}

export type DashboardV2MathTransformApiMode =
    | (typeof DashboardV2MathTransformApiMode)[keyof typeof DashboardV2MathTransformApiMode]
    | null

export const DashboardV2MathTransformApiMode = {
    Value: 'value',
    Series: 'series',
} as const

export interface DashboardV2MathTransformApi {
    type: 'math'
    as: string
    expression: string
    mode?: DashboardV2MathTransformApiMode
}

export interface DashboardV2ThresholdApi {
    value: number
    color: string
    label?: string | null
}

export type DashboardV2ColorSchemeApiSeriesBy =
    | (typeof DashboardV2ColorSchemeApiSeriesBy)[keyof typeof DashboardV2ColorSchemeApiSeriesBy]
    | null

export const DashboardV2ColorSchemeApiSeriesBy = {
    Last: 'last',
    Mean: 'mean',
    Max: 'max',
    Min: 'min',
} as const

export interface DashboardV2ColorSchemeApi {
    mode: string
    fixedColor?: string | null
    seriesBy?: DashboardV2ColorSchemeApiSeriesBy
}

export type DashboardV2FieldOverrideApiStyle =
    | (typeof DashboardV2FieldOverrideApiStyle)[keyof typeof DashboardV2FieldOverrideApiStyle]
    | null

export const DashboardV2FieldOverrideApiStyle = {
    Line: 'line',
    Bars: 'bars',
    Points: 'points',
} as const

export type DashboardV2FieldOverrideApiAxis =
    | (typeof DashboardV2FieldOverrideApiAxis)[keyof typeof DashboardV2FieldOverrideApiAxis]
    | null

export const DashboardV2FieldOverrideApiAxis = {
    Left: 'left',
    Right: 'right',
} as const

export type DashboardV2FieldOverrideApiCell =
    | (typeof DashboardV2FieldOverrideApiCell)[keyof typeof DashboardV2FieldOverrideApiCell]
    | null

export const DashboardV2FieldOverrideApiCell = {
    Bar: 'bar',
    ColorBackground: 'color-background',
    ColorText: 'color-text',
} as const

export interface DashboardV2MappingApi {
    value?: string | null
    from?: number | null
    to?: number | null
    null?: boolean | null
    text?: string | null
    color?: string | null
}

export interface DashboardV2FieldOverrideApi {
    unit?: string | null
    decimals?: number | null
    color?: string | null
    displayName?: string | null
    hidden?: boolean | null
    style?: DashboardV2FieldOverrideApiStyle
    stack?: boolean | null
    fill?: number | null
    dash?: number[] | null
    width?: number | null
    axis?: DashboardV2FieldOverrideApiAxis
    negate?: boolean | null
    cell?: DashboardV2FieldOverrideApiCell
    link?: string | null
    wrap?: boolean | null
    mappings?: DashboardV2MappingApi[] | null
}

export type DashboardV2FieldConfigApiOverrides = { [key: string]: DashboardV2FieldOverrideApi } | null

export interface DashboardV2FieldConfigApi {
    unit?: string | null
    decimals?: number | null
    min?: number | null
    max?: number | null
    softMin?: number | null
    softMax?: number | null
    thresholds?: DashboardV2ThresholdApi[] | null
    color?: DashboardV2ColorSchemeApi | null
    overrides?: DashboardV2FieldConfigApiOverrides
    mappings?: DashboardV2MappingApi[] | null
}

export interface DashboardV2PanelCacheApi {
    ttl?: string | null
}

export type DashboardV2PanelApiIncomplete =
    | (typeof DashboardV2PanelApiIncomplete)[keyof typeof DashboardV2PanelApiIncomplete]
    | null

export const DashboardV2PanelApiIncomplete = {
    Solid: 'solid',
    Dashed: 'dashed',
    Estimate: 'estimate',
    Hidden: 'hidden',
} as const

export interface DashboardV2UrlActionApi {
    type: 'url'
    url: string
    newTab?: boolean | null
}

export type DashboardV2DashboardActionApiTime =
    | (typeof DashboardV2DashboardActionApiTime)[keyof typeof DashboardV2DashboardActionApiTime]
    | null

export const DashboardV2DashboardActionApiTime = {
    Keep: 'keep',
    Clicked: 'clicked',
} as const

export type DashboardV2DashboardActionApiVars = { [key: string]: string } | null

export interface DashboardV2DashboardActionApi {
    type: 'dashboard'
    uid: string
    vars?: DashboardV2DashboardActionApiVars
    time?: DashboardV2DashboardActionApiTime
}

export interface DashboardV2VariableActionApi {
    type: 'variable'
    name: string
    value: string
}

export type DashboardV2PanelActionApiTime =
    | (typeof DashboardV2PanelActionApiTime)[keyof typeof DashboardV2PanelActionApiTime]
    | null

export const DashboardV2PanelActionApiTime = {
    Clicked: 'clicked',
    Dashboard: 'dashboard',
} as const

export type DashboardV2PanelActionApiPanel = { [key: string]: unknown }

export interface DashboardV2PanelActionApi {
    type: 'panel'
    panel: DashboardV2PanelActionApiPanel
    time?: DashboardV2PanelActionApiTime
}

export const DashboardV2PeopleActionApiValue = {
    type: 'people',
} as const
export type DashboardV2PeopleActionApi = typeof DashboardV2PeopleActionApiValue

export const DashboardV2EventsActionApiValue = {
    type: 'events',
} as const
export type DashboardV2EventsActionApi = typeof DashboardV2EventsActionApiValue

export const DashboardV2ZoomActionApiValue = {
    type: 'zoom',
} as const
export type DashboardV2ZoomActionApi = typeof DashboardV2ZoomActionApiValue

export const DashboardV2ExploreActionApiValue = {
    type: 'explore',
} as const
export type DashboardV2ExploreActionApi = typeof DashboardV2ExploreActionApiValue

export interface DashboardV2DrilldownApi {
    title: string
    action:
        | DashboardV2UrlActionApi
        | DashboardV2DashboardActionApi
        | DashboardV2VariableActionApi
        | DashboardV2PanelActionApi
        | DashboardV2PeopleActionApi
        | DashboardV2EventsActionApi
        | DashboardV2ZoomActionApi
        | DashboardV2ExploreActionApi
}

export interface DashboardV2PanelApi {
    title?: string | null
    description?: string | null
    descriptionMode?: DashboardV2PanelApiDescriptionMode
    hideWhenEmpty?: boolean | null
    viz: DashboardV2VizApi
    targets?: DashboardV2TargetApi[] | null
    transforms?:
        | (
              | DashboardV2PartitionTransformApi
              | DashboardV2OrganizeTransformApi
              | DashboardV2MergeTransformApi
              | DashboardV2LimitTransformApi
              | DashboardV2SortTransformApi
              | DashboardV2RenameTransformApi
              | DashboardV2MathTransformApi
          )[]
        | null
    fieldConfig?: DashboardV2FieldConfigApi | null
    cache?: DashboardV2PanelCacheApi | null
    precompute?: boolean | null
    interval?: string | null
    timeFrom?: string | null
    timeShift?: string | null
    compare?: string | null
    incomplete?: DashboardV2PanelApiIncomplete
    drilldowns?: DashboardV2DrilldownApi[] | null
    links?: DashboardV2DashboardLinkApi[] | null
    maxDataPoints?: number | null
    builder?: DashboardV2BuilderStateApi | null
    requires?: string[] | null
}

export type DashboardV2RequirementKindEnumApi =
    (typeof DashboardV2RequirementKindEnumApi)[keyof typeof DashboardV2RequirementKindEnumApi]

export const DashboardV2RequirementKindEnumApi = {
    Event: 'event',
    Sdk: 'sdk',
    Warehouse: 'warehouse',
    Metric: 'metric',
    Query: 'query',
} as const

export type DashboardV2RequirementApiLanguage =
    | (typeof DashboardV2RequirementApiLanguage)[keyof typeof DashboardV2RequirementApiLanguage]
    | null

export const DashboardV2RequirementApiLanguage = {
    Promql: 'promql',
    Hogql: 'hogql',
    Sql: 'sql',
    Logql: 'logql',
    Insight: 'insight',
} as const

export interface DashboardV2RequirementApi {
    /** @pattern ^[a-z0-9][a-z0-9_-]*$ */
    id: string
    /**
     * @minLength 1
     * @maxLength 300
     */
    title: string
    kind: DashboardV2RequirementKindEnumApi
    why?: string | null
    optional?: boolean | null
    event?: string | null
    bind?: string | null
    property?: string | null
    table?: string | null
    metric?: string | null
    language?: DashboardV2RequirementApiLanguage
    query?: string | null
    setup?: string | null
}

export type DashboardV2SpecApiPanels = { [key: string]: DashboardV2PanelApi }

export interface DashboardV2SpecApi {
    /** @pattern ^[a-z0-9][a-z0-9_-]{1,62}$ */
    uid: string
    /**
     * @minLength 1
     * @maxLength 300
     */
    title: string
    description?: string | null
    folder?: string | null
    tags?: string[] | null
    links?: DashboardV2DashboardLinkApi[] | null
    linkStyle?: DashboardV2SpecApiLinkStyle
    display?: DashboardV2SpecApiDisplay
    time?: DashboardV2TimeRangeApi
    refresh?: string | null
    timezone?: string | null
    variables?: (
        | DashboardV2CustomVariableApi
        | DashboardV2QueryVariableApi
        | DashboardV2TextboxVariableApi
        | DashboardV2IntervalVariableApi
        | DashboardV2ConstantVariableApi
        | DashboardV2AdhocVariableApi
    )[]
    layout: DashboardV2LayoutApi
    panels: DashboardV2SpecApiPanels
    requires?: DashboardV2RequirementApi[] | null
}

export interface CreateDashboardV2InputApi {
    /** The dashboard document. Its `uid` becomes the uid of the dashboard and must be unused in the project. */
    spec: DashboardV2SpecApi
}

export interface DashboardV2DetailApi {
    /** Unique identifier of the dashboard row. API routes use `uid`. */
    id: string
    /** Identifier of the dashboard in URLs and in its spec. It is unique in the project. */
    uid: string
    /** Title from the spec. */
    title: string
    /**
     * Description from the spec, or null when the spec has none.
     * @nullable
     */
    description: string | null
    /** Folder titles from the spec, separated by `/`. Empty for the top level. */
    folder: string
    /** Tags from the spec. */
    tags: string[]
    /** Number of the latest saved version. It starts at 1, and each save adds 1. */
    version: number
    /** When the dashboard was created. */
    created_at: string
    /** User who created the dashboard, or null when unknown. */
    readonly created_by: UserBasicApi | null
    /** When the dashboard was last saved. */
    last_modified_at: string
    /** User who last saved the dashboard, or null when unknown. */
    readonly last_modified_by: UserBasicApi | null
    /** The dashboard document: its variables, layout and panels. Its keys are camelCase. */
    spec: DashboardV2SpecApi
}

export interface DashboardV2SpecIssueApi {
    /** Where the problem is in the spec, for example `panels.orders.viz.type`. */
    path: string
    /** What is wrong at that path. */
    message: string
}

export interface DashboardV2InvalidSpecExtraApi {
    /** Every problem found in the spec. */
    issues: DashboardV2SpecIssueApi[]
}

export interface DashboardV2InvalidSpecErrorApi {
    /** Error category. Always `validation_error`. */
    type: string
    /** Error code. `invalid_spec` when the spec has the problems in `extra`. */
    code: string
    /** The problems as one readable message. */
    detail: string
    /**
     * Request field the error is about.
     * @nullable
     */
    attr: string | null
    /** Present when `code` is `invalid_spec`. */
    extra?: DashboardV2InvalidSpecExtraApi
}

export interface UpdateDashboardV2InputApi {
    /** The whole dashboard document to save as the next version. Its `uid` must match the URL. */
    spec: DashboardV2SpecApi
    /**
     * The `version` this save is based on. The save is refused with a 409 when the dashboard has a different version. Leave it out to save over any version.
     * @minimum 1
     * @nullable
     */
    base_version?: number | null
    /** A note on what changed, stored with the new version. */
    message?: string
}

export type DashboardsV2ListParams = {
    /**
     * Number of results to return per page.
     * @maximum 1000
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Return only dashboards whose title contains this text, ignoring case.
     */
    search?: string
}
