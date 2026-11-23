// Per kind, what `check` needs: the tool whose input schema validates a body, what a ref to the
// kind can read, which body positions take a ref, and how keys are formed. The engine's half of each
// kind lives in `products/stacks/backend/engine/mapping/<kind>.json`, and a conformance test there
// holds the two halves together.
import type { JsonObject, JsonValue } from '../types.js'

export type IdType = 'number' | 'string'

export interface RefPosition {
    // As `insight`, `dashboards[]` or `tiles[].insight`.
    path: string
    kinds: readonly string[]
    // The position also takes an id written out, for an entity the stack doesn't define. `uuid`
    // accepts a UUID, `string` any text, `number` a positive whole number.
    literal?: 'uuid' | 'string' | 'number'
    // The field of the target the position takes. Defaults to `id`.
    attr?: string
    nullable?: boolean
}

export interface RuleIssue {
    code?: string
    path?: string
    message: string
    severity?: 'error' | 'warning'
}

// A field the API accepts that the MCP schema strips. Each is named, so the default stays strict.
export interface SchemaGap {
    name: string
    // As `query.chartSettings.goalLines[].position`. Covers everything below it too.
    path: string
    // Only where this holds for the value at the path, such as one kind of series.
    when?: (value: JsonValue | undefined) => boolean
}

export type QuerySchema =
    | { tool: string; input: JsonObject; prefix: (string | number)[] }
    | { unchecked: string; path: string }

// How a body becomes the tool's input, for a tool whose input wraps the body.
export interface ToolInput {
    input: JsonObject
    // The body path a path in the tool input stands for.
    bodyPath(inputPath: string): string
    // The body fields the tool kept, from the input it accepted.
    acceptedFields(accepted: Record<string, unknown>): Set<string>
}

export interface StructuralIssue {
    path: string
    message: string
}

export interface KindSpec {
    kind: string
    // The words for the kind in messages.
    label: string
    // The MCP tool whose input schema is the kind's create body.
    tool: string
    // Set while the tool is declared in a tools.yaml but not generated yet, or is hidden behind a
    // feature flag in the bundled catalog. `check` then runs `structural` instead of the tool.
    toolPending?: string
    structural?: (body: JsonObject) => StructuralIssue[]
    toInput?: (body: JsonObject) => ToolInput
    // The fields a ref may read, with the type a placeholder takes in their place. `id` comes first.
    attrs: Readonly<Record<string, IdType>>
    refs: readonly RefPosition[]
    // Body fields left out of the tool's schema check: the SDK adds them, and the engine maps them.
    composed?: readonly string[]
    // Fields the create input has that are steps of the call, not part of the entity. A body with one fails.
    omitted?: readonly string[]
    // Body subtrees where a ref of any kind may sit, such as a destination's inputs.
    freeRefs?: readonly string[]
    schemaGaps?: readonly SchemaGap[]
    // Rules PostHog's backend enforces that the schema can't express.
    rules?: (body: JsonObject) => RuleIssue[]
    // Further schemas for parts of the body, such as an insight's query by its kind.
    querySchemas?: (body: JsonObject) => QuerySchema[]
    // Body subtrees PostHog stores as written, such as an insight's query. A key the schema check
    // doesn't know there is kept, so check warns about it instead of failing.
    keptAsWritten?: readonly string[]
    // A kind with a natural key (an event name, a flag key) checks keys with its own rule, and
    // the key repeats in the body under `field`.
    naturalKey?: NaturalKey
}

// The API's naming rule for a kind whose key is a natural key. `pattern` and `maxLength` are the same
// text as `key_pattern` and `key_max_length` in the engine's mapping file for the kind, and a test
// holds the two together.
export interface NaturalKey {
    // A regular expression source, matched against the whole key with Unicode semantics.
    pattern: string
    // In Unicode code points.
    maxLength: number
    rule: string
    field: string
    reserved?: readonly string[]
    reservedPrefixes?: readonly string[]
}

export const KEY_PATTERN = /^[a-z0-9][a-z0-9_-]*$/
export const KEY_MAX_LENGTH = 100
export const KEY_RULE = 'lowercase letters, digits, "_" and "-", starting with a letter or digit'

const isObject = (value: JsonValue | undefined): value is JsonObject =>
    typeof value === 'object' && value !== null && !Array.isArray(value)

// A property's `enum` feeds the generated types and never reaches PostHog, so the schema has no
// field for it and its shape is checked here.
function propertyEnumShape(body: JsonObject): StructuralIssue[] {
    if (!Array.isArray(body.properties)) {
        return []
    }
    return body.properties.flatMap((property, index) => {
        const values = isObject(property) ? property.enum : undefined
        return values === undefined || (Array.isArray(values) && values.every((value) => typeof value === 'string'))
            ? []
            : [{ path: `properties[${index}].enum`, message: `properties[${index}].enum must be a list of strings.` }]
    })
}

// A HogQL placeholder for an endpoint variable, as `{variables.account_id}`.
const VARIABLE_PLACEHOLDER = /\{\s*variables\.([A-Za-z_][A-Za-z0-9_]*)\s*\}/g
const VARIABLE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

// The endpoint API (`validate_variable_placeholders` in `products/endpoints/backend/logic/validation.py`)
// matches each placeholder to a variable in `query.variables` by its code name, and first fills in
// any it can find among the project's SQL variables by code name. A placeholder neither covers is refused.
function endpointRules(body: JsonObject): RuleIssue[] {
    const query = body.query
    if (!isObject(query) || query.kind !== 'HogQLQuery' || typeof query.query !== 'string') {
        return []
    }
    const variables = isObject(query.variables) ? query.variables : {}
    const declared = new Set(
        Object.values(variables).flatMap((variable) =>
            isObject(variable) && typeof variable.code_name === 'string' ? [variable.code_name] : []
        )
    )
    const issues: RuleIssue[] = []
    const named = new Set([...query.query.matchAll(VARIABLE_PLACEHOLDER)].map((match) => match[1] as string))
    for (const name of [...named].sort()) {
        if (!declared.has(name)) {
            issues.push({
                code: 'variable_undeclared',
                severity: 'warning',
                path: 'query.query',
                message: `The query reads {variables.${name}}, and query.variables declares no variable with the code name ${name}. PostHog refuses the endpoint unless the project already has a SQL variable named ${name}.`,
            })
        }
    }
    for (const id of Object.keys(variables).sort()) {
        if (!VARIABLE_ID.test(id)) {
            issues.push({
                code: 'variable_invalid',
                path: `query.variables.${id}`,
                message: `query.variables.${id} must be keyed by the id of a SQL variable, a UUID. PostHog refuses any other key.`,
            })
        }
    }
    return issues
}

// The wiki lints every page it lands (`products/context_layer/backend/repo_lint.py`). These are its
// per-page rules that a page's own text decides; a replacement page that must exist, and titles
// already in the wiki, are outside what check can see.
const WIKI_STATUSES = ['active', 'superseded', 'historical']
const WIKI_PAGE_MAX_BYTES = 1_000_000
const WIKILINK = /\[\[([^[\]\n]+)\]\]/

export function wikiFrontmatter(content: string): Map<string, string> {
    const lines = content.split(/\r?\n/)
    const fields = new Map<string, string>()
    if (lines[0]?.trim() !== '---') {
        return fields
    }
    const end = lines.findIndex((line, index) => index > 0 && line.trim() === '---')
    for (const line of end > 0 ? lines.slice(1, end) : []) {
        const separator = line.indexOf(':')
        const key = separator >= 0 ? line.slice(0, separator) : ''
        if (key && key === key.trim()) {
            fields.set(key, line.slice(separator + 1).trim())
        }
    }
    return fields
}

// The page's first `# ` heading, normalized the way the wiki compares titles.
export function wikiTitle(content: string): string | undefined {
    const heading = /^#\s+(.+?)\s*$/m.exec(content)?.[1]
    return heading
        ?.toLowerCase()
        .replace(/[^a-z0-9]+/g, ' ')
        .trim()
}

function isoDate(value: string): boolean {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
    if (!match) {
        return false
    }
    const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])))
    return date.getUTCMonth() === Number(match[2]) - 1 && date.getUTCDate() === Number(match[3])
}

function contextPageRules(body: JsonObject): RuleIssue[] {
    const { path, content } = body
    if (typeof path !== 'string' || typeof content !== 'string' || path === 'AGENTS.md' || path.endsWith('/index.md')) {
        return []
    }
    const refused = (rule: string, fix: string): RuleIssue => ({
        code: 'context_page_refused',
        path: 'content',
        message: `The wiki refuses this page: ${rule}. ${fix}`,
    })
    const issues: RuleIssue[] = []
    if (new TextEncoder().encode(content).length > WIKI_PAGE_MAX_BYTES) {
        issues.push(refused('page content exceeds the 1 MB limit', 'Split it into several pages.'))
    }
    const fields = wikiFrontmatter(content)
    const between = 'between --- lines at the top of the page'
    if (!fields.get('summary')) {
        issues.push(refused('frontmatter needs a one-line `summary`', `Add \`summary: ...\` ${between}.`))
    }
    const status = fields.get('status')
    if (!status || !WIKI_STATUSES.includes(status)) {
        issues.push(
            refused(
                'frontmatter `status` must be active, superseded, or historical',
                `Add \`status: active\` ${between}, or one of the others.`
            )
        )
    }
    const reviewAfter = fields.get('review_after')
    if (reviewAfter && !isoDate(reviewAfter)) {
        issues.push(refused('frontmatter `review_after` must be an ISO date', 'Write it as YYYY-MM-DD.'))
    }
    if (path.startsWith('decisions/') && !fields.get('sources')) {
        issues.push(refused('decision pages need non-empty `sources` frontmatter', `Add \`sources: ...\` ${between}.`))
    }
    const parts = path.split('/')
    if (parts[0] === 'projects' && parts.length === 4 && parts[2] === 'spaces') {
        if (!fields.get('channel_id')) {
            issues.push(
                refused(
                    'Space pages need a non-empty `channel_id` in their frontmatter',
                    `Add \`channel_id: ...\` ${between}.`
                )
            )
        }
        if (fields.get('team_id') !== parts[1]) {
            issues.push(refused(`Space pages need \`team_id: ${parts[1]}\` in their frontmatter`, `Add it ${between}.`))
        }
    }
    if (status === 'superseded' && !WIKILINK.test(content)) {
        issues.push(
            refused(
                'superseded pages must wikilink an existing replacement',
                'Link the page that replaces it, as [[path/to/page]].'
            )
        )
    }
    return issues
}

// Temporary: the context wiki tools are behind the `context-layer` flag, so the bundled catalog
// has no schema for them. These are the API serializer's rules.
function contextPageShape(body: JsonObject): StructuralIssue[] {
    const issues: StructuralIssue[] = []
    if (typeof body.path !== 'string' || body.path.length > 512) {
        issues.push({ path: 'path', message: 'path must be a string of at most 512 characters.' })
    }
    if (typeof body.content !== 'string') {
        issues.push({ path: 'content', message: 'content must be the Markdown text of the page.' })
    }
    return issues
}

const EVENT_DATA_FIELDS = ['description', 'owner', 'tags', 'verified', 'hidden', 'enforcement_mode']

// The event-definition tool takes `{ eventName, data }`.
function eventInput(body: JsonObject): ToolInput {
    const data = Object.fromEntries(Object.entries(body).filter(([name]) => EVENT_DATA_FIELDS.includes(name)))
    return {
        input: { eventName: body.name ?? null, ...(Object.keys(data).length > 0 ? { data } : {}) },
        bodyPath: (path) => (path === 'eventName' ? 'name' : path.replace(/^data\.?/, '')),
        acceptedFields: (accepted) => new Set(['name', ...Object.keys((accepted.data as object | undefined) ?? {})]),
    }
}

// The backend refuses an absolute threshold with neither bound.
function alertRules(body: JsonObject): RuleIssue[] {
    const threshold = body.threshold
    const configuration = isObject(threshold) ? threshold.configuration : undefined
    if (!isObject(configuration) || configuration.type !== 'absolute') {
        return []
    }
    const bounds = configuration.bounds
    const has = (name: string): boolean => isObject(bounds) && typeof bounds[name] === 'number'
    return has('lower') || has('upper')
        ? []
        : [
              {
                  code: 'threshold_bounds_missing',
                  path: 'threshold.configuration.bounds',
                  message: 'An absolute threshold needs a lower or an upper bound, or both.',
              },
          ]
}

const CREDENTIAL = /(password|secret|token|api_?key|private_?key|credential)/i

// No secret goes in the code: a source names its credentials with secret('NAME').
function sourceRules(body: JsonObject): RuleIssue[] {
    const payload = body.payload
    if (!isObject(payload)) {
        return []
    }
    return Object.entries(payload)
        .filter(([name, value]) => CREDENTIAL.test(name) && typeof value === 'string' && value !== '')
        .map(([name]) => ({
            code: 'secret_inline',
            path: `payload.${name}`,
            message: `payload.${name} holds a credential as plain text. Use secret('NAME'), and set the value in PostHog.`,
        }))
}

const kindOf = (value: JsonValue | undefined): unknown => (isObject(value) ? value.kind : undefined)

// The query runner reads an optional field set to null as unset, as stored insights often have it.
function withoutNulls(value: JsonValue): JsonValue {
    if (Array.isArray(value)) {
        return value.map(withoutNulls)
    }
    if (isObject(value)) {
        return Object.fromEntries(
            Object.entries(value)
                .filter(([, item]) => item !== null)
                .map(([name, item]) => [name, withoutNulls(item)])
        )
    }
    return value
}

const QUERY_TOOLS: Readonly<Record<string, string>> = {
    TrendsQuery: 'query-trends',
    FunnelsQuery: 'query-funnel',
    RetentionQuery: 'query-retention',
    PathsQuery: 'query-paths',
    StickinessQuery: 'query-stickiness',
    LifecycleQuery: 'query-lifecycle',
}

// `insight-create` takes any object as an `InsightVizNode`'s source, so the source also goes
// through the query tool for its kind.
// `InsightVizNode`'s boolean switches in PostHog's query schema, besides `showHeader`.
const INSIGHT_NODE_SWITCHES = [
    'embedded',
    'full',
    'hidePersonsModal',
    'hideTooltipOnScroll',
    'showCorrelationTable',
    'showFilters',
    'showLastComputation',
    'showLastComputationRefresh',
    'showResults',
    'showTable',
    'suppressSessionAnalysisWarning',
    'version',
]

function insightQuerySchemas(body: JsonObject): QuerySchema[] {
    const query = body.query
    if (!isObject(query) || query.kind !== 'InsightVizNode' || !isObject(query.source)) {
        return []
    }
    const kind = query.source.kind
    const tool = typeof kind === 'string' ? QUERY_TOOLS[kind] : undefined
    return tool
        ? [{ tool, input: withoutNulls(query.source) as JsonObject, prefix: ['query', 'source'] }]
        : [
              {
                  path: 'query.source.kind',
                  unchecked: `check has no schema for the query kind ${String(kind)}, so it didn't validate the query. It knows ${Object.keys(QUERY_TOOLS).join(', ')}.`,
              },
          ]
}

// An event or property group name: any text, including inner spaces and Unicode, that is neither
// blank nor starts or ends with whitespace, and has no NUL.
const SPACE = '\\x00\\x09-\\x0d\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000'
const NAME_LIKE = {
    pattern: `^[^${SPACE}](?:[^\\x00]*[^${SPACE}])?$`,
    rule: 'any text without a NUL that does not start or end with whitespace',
    maxLength: 400,
}

const KINDS: readonly KindSpec[] = [
    {
        kind: 'insight',
        label: 'insight',
        tool: 'insight-create',
        attrs: { id: 'number', short_id: 'string', name: 'string' },
        // A dashboard outside the stack is named by its id.
        refs: [{ path: 'dashboards[]', kinds: ['dashboard'], literal: 'number' }],
        // Shapes PostHog stores and runs that the MCP insight and query-wrapper schemas don't cover.
        schemaGaps: [
            { name: 'goal line position', path: 'query.chartSettings.goalLines[].position' },
            { name: 'derived name', path: 'derived_name' },
            // The engine reads an adopted insight's deleted state, and the API takes it.
            { name: 'deleted state', path: 'deleted' },
            // Display switches of an insight node, all in PostHog's query schema.
            ...INSIGHT_NODE_SWITCHES.map((name) => ({ name: 'insight display switch', path: `query.${name}` })),
            // PostHog's query schema makes the breakdown list optional; the trends tool's schema requires it.
            {
                name: 'breakdown without a breakdown list',
                path: 'query.source.breakdownFilter.breakdowns',
                when: (value) => value === undefined,
            },
            // PostHog's query schema takes a property group where the tools take only a list of filters.
            {
                name: 'property group filter',
                path: 'query.source.properties',
                when: (value) =>
                    isObject(value) && (value.type === 'AND' || value.type === 'OR') && Array.isArray(value.values),
            },
            { name: 'insight header switch', path: 'query.showHeader' },
            { name: 'query version', path: 'query.source.version' },
            { name: 'explicit date range', path: 'query.source.dateRange.explicitDate' },
            { name: 'sampling factor', path: 'query.source.samplingFactor' },
            {
                name: 'warehouse series',
                path: 'query.source.series[]',
                when: (value) => kindOf(value) === 'DataWarehouseNode',
            },
            {
                name: 'SQL data table',
                path: 'query',
                when: (value) =>
                    kindOf(value) === 'DataTableNode' &&
                    kindOf(isObject(value) ? value.source : undefined) === 'HogQLQuery',
            },
        ],
        querySchemas: insightQuerySchemas,
        // The insight API saves a query node as written.
        keptAsWritten: ['query'],
    },
    {
        kind: 'dashboard',
        label: 'dashboard',
        tool: 'dashboard-create',
        attrs: { id: 'number', name: 'string' },
        refs: [{ path: 'tiles[].insight', kinds: ['insight'], attr: 'id' }],
        composed: ['tiles'],
        omitted: ['use_template', 'use_dashboard', 'delete_insights'],
    },
    {
        kind: 'alert',
        label: 'alert',
        tool: 'alert-create',
        attrs: { id: 'string', name: 'string' },
        refs: [{ path: 'insight', kinds: ['insight'], attr: 'id' }],
        rules: alertRules,
    },
    {
        kind: 'destination',
        label: 'destination',
        tool: 'cdp-functions-create',
        attrs: { id: 'string', name: 'string' },
        refs: [],
        freeRefs: ['inputs', 'filters'],
    },
    {
        kind: 'flag',
        label: 'flag',
        tool: 'create-feature-flag',
        attrs: { id: 'number', key: 'string', name: 'string' },
        refs: [],
        naturalKey: { pattern: '^[A-Za-z0-9_-]+$', rule: 'letters, digits, "_" and "-"', maxLength: 400, field: 'key' },
    },
    { kind: 'cohort', label: 'cohort', tool: 'cohorts-create', attrs: { id: 'number', name: 'string' }, refs: [] },
    { kind: 'action', label: 'action', tool: 'action-create', attrs: { id: 'number', name: 'string' }, refs: [] },
    {
        kind: 'event',
        label: 'event',
        tool: 'event-definition-create',
        toInput: eventInput,
        attrs: { id: 'string', name: 'string' },
        refs: [{ path: 'property_groups[]', kinds: ['property_group'], attr: 'id' }],
        composed: ['property_groups'],
        naturalKey: { ...NAME_LIKE, field: 'name' },
    },
    {
        kind: 'property_group',
        label: 'property group',
        tool: 'schema-property-group-create',
        structural: propertyEnumShape,
        schemaGaps: [{ name: 'values for generated types', path: 'properties[].enum' }],
        attrs: { id: 'string', name: 'string' },
        refs: [],
        naturalKey: { ...NAME_LIKE, field: 'name' },
    },
    {
        kind: 'model',
        label: 'model',
        tool: 'view-create',
        attrs: { id: 'string', name: 'string' },
        refs: [],
        composed: ['is_materialized', 'columns'],
        omitted: ['folder_id', 'acknowledge_breaking_changes', 'is_test'],
        naturalKey: {
            pattern: '^[A-Za-z_$][A-Za-z0-9_.$]*$',
            rule: 'letters, digits, "_", "." and "$", starting with a letter, "_" or "$"',
            maxLength: 128,
            field: 'name',
            reserved: ['models', 'system'],
            reservedPrefixes: ['system.'],
        },
    },
    {
        kind: 'endpoint',
        label: 'endpoint',
        tool: 'endpoint-create',
        attrs: { id: 'string', name: 'string' },
        refs: [],
        rules: endpointRules,
        naturalKey: {
            pattern: '^[A-Za-z][A-Za-z0-9_-]*$',
            rule: 'letters, digits, "_" and "-", starting with a letter',
            maxLength: 128,
            field: 'name',
            reserved: ['bulk_update_tags', 'last_execution_times'],
        },
    },
    {
        kind: 'source',
        label: 'warehouse source',
        tool: 'external-data-sources-create',
        attrs: { id: 'string' },
        refs: [],
        rules: sourceRules,
    },
    {
        kind: 'metric',
        label: 'metric',
        tool: 'data-catalog-metric-create',
        attrs: { id: 'string', name: 'string' },
        refs: [
            {
                path: 'source_insight_short_id',
                kinds: ['insight'],
                literal: 'string',
                attr: 'short_id',
                nullable: true,
            },
        ],
        omitted: ['overwrite'],
        naturalKey: {
            pattern: '^[A-Za-z][A-Za-z0-9_]*$',
            rule: 'letters, digits and "_", starting with a letter',
            maxLength: 128,
            field: 'name',
            reserved: ['bulk_approve', 'bulk_delete'],
        },
    },
    {
        kind: 'check',
        label: 'data quality check',
        tool: 'data-quality-check-create',
        attrs: { id: 'string', name: 'string' },
        refs: [{ path: 'subject_uuid', kinds: ['model'], literal: 'uuid', attr: 'id' }],
    },
    {
        kind: 'context_page',
        label: 'context page',
        tool: 'context-wiki-page-update',
        toolPending: 'behind the context-layer feature flag, so the bundled catalog has no schema for it',
        structural: contextPageShape,
        rules: contextPageRules,
        attrs: { path: 'string' },
        refs: [],
        omitted: ['base_head'],
        naturalKey: {
            pattern:
                '^(?![^\\x00]*(?:/\\.{1,2}/|/\\.git/|//|/index\\.md$))(?:AGENTS\\.md|(?:org|areas|projects)/(?:[^/\\x00]+/)*[^/\\x00]+\\.md|decisions/(?:[^/\\x00]+/)*[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9][a-z0-9-]*\\.md)$',
            rule: 'AGENTS.md, a .md path under org/, areas/ or projects/, or a dated decision under decisions/, other than an index.md',
            maxLength: 512,
            field: 'path',
        },
    },
    {
        kind: 'experiment',
        label: 'experiment',
        tool: 'experiment-create',
        attrs: { id: 'number', name: 'string' },
        refs: [],
    },
    {
        kind: 'survey',
        label: 'survey',
        tool: 'survey-create',
        attrs: { id: 'string', name: 'string' },
        refs: [{ path: 'linked_flag_id', kinds: ['flag'], attr: 'id', nullable: true }],
    },
]

const BY_KIND: ReadonlyMap<string, KindSpec> = new Map(KINDS.map((spec) => [spec.kind, spec]))

export function kindSpec(kind: string): KindSpec | undefined {
    return BY_KIND.get(kind)
}

export function knownKinds(): string[] {
    return KINDS.map((spec) => spec.kind)
}

// The tool that validates a text tile's body.
export const TILE_TOOL = 'dashboard-create-tile'
