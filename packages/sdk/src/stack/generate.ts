import { hogqlIdentifier } from '../define/model.js'
import type { JsonObject, JsonValue } from '../types.js'
import { compareResources, isRefValue, type ResourceDescription } from './description.js'
import { resourceId } from './evaluate.js'

export interface GeneratedFile {
    // Relative to the stack folder, with forward slashes.
    path: string
    contents: string
}

export interface GenerateOptions {
    // `kind:key` of definitions the folder already has. They are not generated again, and a
    // generated definition refers to them with `ref(kind, key)`.
    existingKeys?: Iterable<string>
}

// Which file each kind's definitions go in.
const FAMILIES: Readonly<Record<string, string>> = {
    event: 'events',
    property_group: 'events',
    flag: 'flags',
    experiment: 'flags',
    survey: 'flags',
    cohort: 'people',
    action: 'people',
    model: 'models',
    endpoint: 'endpoints',
    source: 'sources',
    metric: 'metrics',
    check: 'metrics',
    insight: 'views',
    dashboard: 'views',
    alert: 'alerts',
    destination: 'alerts',
    context_page: 'context',
}

const FAMILY_ORDER = [
    'events',
    'models',
    'people',
    'flags',
    'endpoints',
    'sources',
    'metrics',
    'views',
    'alerts',
    'context',
]

const RESERVED = new Set(
    'break case catch class const continue debugger default delete do else enum export extends false finally for function if import in instanceof let new null return super switch this throw true try typeof var void while with yield await implements interface package private protected public static'.split(
        ' '
    )
)

const IDENTIFIER = /^[A-Za-z_$][A-Za-z0-9_$]*$/

function camel(key: string): string {
    const words = key.split(/[^A-Za-z0-9]+/).filter(Boolean)
    const name = words
        .map((word, index) =>
            index === 0 ? word.charAt(0).toLowerCase() + word.slice(1) : word.charAt(0).toUpperCase() + word.slice(1)
        )
        .join('')
    const safe = /^[0-9]/.test(name) || name === '' ? `the${name.charAt(0).toUpperCase()}${name.slice(1)}` : name
    return RESERVED.has(safe) ? `${safe}Definition` : safe
}

interface Planned {
    resource: ResourceDescription
    name: string
    family: string
    // Set on a property group that its event writes inline.
    inline?: boolean
}

interface Context {
    plans: Map<string, Planned>
    // The definition being written, and the file it goes in.
    current: Planned
    imports: Map<string, Set<string>>
    uses: Set<string>
    // Refs that point at a definition written later in the same file, or across a file cycle.
    deferred: Set<string>
    // How many resources refer to each `kind:key`.
    referrers: Map<string, number>
}

function quoteString(value: string): string {
    if (value.includes('\n')) {
        return `\`${value.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$\{/g, '\\${')}\``
    }
    return `'${value.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\r/g, '\\r').replace(/\t/g, '\\t')}'`
}

function quoteKey(name: string): string {
    return IDENTIFIER.test(name) ? name : quoteString(name)
}

function refText(value: { $ref: { kind: string; key: string; attr?: string } }, context: Context): string {
    const { kind, key, attr } = value.$ref
    const id = resourceId(kind, key)
    const plan = context.plans.get(id)
    if (plan && !context.deferred.has(id)) {
        if (plan.family !== context.current.family) {
            const names = context.imports.get(plan.family) ?? new Set<string>()
            names.add(plan.name)
            context.imports.set(plan.family, names)
        }
        if (attr) {
            context.uses.add('ref')
            return `ref(${plan.name}, ${quoteString(attr)})`
        }
        return plan.name
    }
    context.uses.add('ref')
    return `ref(${quoteString(kind)}, ${quoteString(key)}${attr ? `, ${quoteString(attr)}` : ''})`
}

function render(value: JsonValue | undefined, context: Context, indent: string): string {
    if (value === undefined || value === null) {
        return 'null'
    }
    if (typeof value === 'string') {
        return quoteString(value)
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
        return JSON.stringify(value)
    }
    if (isRefValue(value)) {
        return refText(value, context)
    }
    const inner = `${indent}    `
    if (Array.isArray(value)) {
        if (value.length === 0) {
            return '[]'
        }
        return `[\n${value.map((item) => `${inner}${render(item, context, inner)},`).join('\n')}\n${indent}]`
    }
    if ('$secret' in value && typeof value.$secret === 'string' && Object.keys(value).length === 1) {
        context.uses.add('secret')
        return `secret(${quoteString(value.$secret)})`
    }
    const entries = Object.entries(value)
    if (entries.length === 0) {
        return '{}'
    }
    return `{\n${entries.map(([name, item]) => `${inner}${quoteKey(name)}: ${render(item, context, inner)},`).join('\n')}\n${indent}}`
}

// A query the `sql` tag gives back unchanged: it reads cooked strings, and only dedents text that
// starts with a line break.
function sqlText(query: string): string {
    return `sql\`${query.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$\{/g, '\\${')}\``
}

const IDENTIFIER_CHAR = /[A-Za-z0-9_$`]/

// The query as a `sql` template that interpolates each model it depends on where the query names
// its table, so evaluating it gives the same text and the same `depends_on`. Undefined when no
// dependency can be written that way, such as one that closes a loop of files.
function sqlWithDependencies(query: string, context: Context): string | undefined {
    const models = (context.current.resource.depends_on ?? [])
        .filter((entry) => entry.kind === 'model')
        .flatMap((entry) => {
            const id = resourceId(entry.kind, entry.key)
            return context.plans.has(id) && !context.deferred.has(id)
                ? [{ table: hogqlIdentifier(entry.key), ref: { $ref: { kind: entry.kind, key: entry.key } } }]
                : []
        })
        .sort((a, b) => b.table.length - a.table.length)
    if (models.length === 0) {
        return undefined
    }
    const escape = (text: string): string => text.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$\{/g, '\\${')
    let template = ''
    let pending = ''
    let used = false
    let quoted = false
    for (let at = 0; at < query.length; ) {
        const char = query[at] as string
        if (quoted) {
            pending += char
            if (char === '\\' && at + 1 < query.length) {
                pending += query[at + 1]
                at += 2
                continue
            }
            quoted = char !== "'"
            at += 1
            continue
        }
        if (char === "'") {
            quoted = true
            pending += char
            at += 1
            continue
        }
        const before = at === 0 ? '' : (query[at - 1] as string)
        const match = models.find(
            ({ table }) =>
                query.startsWith(table, at) &&
                !IDENTIFIER_CHAR.test(before) &&
                before !== '.' &&
                !IDENTIFIER_CHAR.test(query[at + table.length] ?? '')
        )
        if (match) {
            template += `${escape(pending)}\${${refText(match.ref, context)}}`
            pending = ''
            used = true
            at += match.table.length
            continue
        }
        pending += char
        at += 1
    }
    if (!used) {
        return undefined
    }
    context.uses.add('sql')
    return `sql\`${template}${escape(pending)}\``
}

function isHogQLNode(value: JsonValue | undefined): value is JsonObject & { query: string } {
    return (
        typeof value === 'object' &&
        value !== null &&
        !Array.isArray(value) &&
        value.kind === 'HogQLQuery' &&
        typeof value.query === 'string' &&
        !value.query.startsWith('\n') &&
        Object.keys(value).length === 2
    )
}

function fieldsText(fields: [string, string][], indent: string): string {
    if (fields.length === 0) {
        return '{}'
    }
    return `{\n${fields.map(([name, text]) => `${indent}    ${quoteKey(name)}: ${text},`).join('\n')}\n${indent}}`
}

function objectFields(body: JsonObject, context: Context, skip: readonly string[] = []): [string, string][] {
    return Object.entries(body)
        .filter(([name]) => !skip.includes(name))
        .map(([name, value]) => [name, render(value, context, '    ')])
}

const PROPERTY_BUILDERS: Readonly<Record<string, string>> = {
    String: 'string',
    Numeric: 'number',
    Boolean: 'boolean',
    DateTime: 'datetime',
    Object: 'object',
    Array: 'array',
}

// The group's properties as `prop` calls, when every property is one `prop` can make.
function propsText(group: JsonObject | undefined): string | undefined {
    if (!group || group.description !== undefined || !Array.isArray(group.properties)) {
        return undefined
    }
    const lines: string[] = []
    for (const property of group.properties) {
        if (property === null || typeof property !== 'object' || Array.isArray(property)) {
            return undefined
        }
        const { name, property_type: type, is_required: required, description, enum: members, ...rest } = property
        if (
            Object.keys(rest).length > 0 ||
            typeof name !== 'string' ||
            typeof type !== 'string' ||
            typeof required !== 'boolean'
        ) {
            return undefined
        }
        if (members !== undefined && (type !== 'String' || !Array.isArray(members))) {
            return undefined
        }
        if (members !== undefined && !members.every((member) => typeof member === 'string')) {
            return undefined
        }
        const builder =
            members !== undefined
                ? `enum([${(members as string[]).map(quoteString).join(', ')}])`
                : PROPERTY_BUILDERS[type]
                  ? `${PROPERTY_BUILDERS[type]}()`
                  : undefined
        if (!builder) {
            return undefined
        }
        lines.push(
            `        ${quoteKey(name)}: prop.${builder}${required ? '.required()' : ''}${typeof description === 'string' ? `.describe(${quoteString(description)})` : ''},`
        )
    }
    return `{\n${lines.join('\n')}\n    }`
}

function eventText(plan: Planned, context: Context): string {
    const body = plan.resource.body
    const groups = Array.isArray(body.property_groups) ? body.property_groups : []
    const own =
        groups.length === 1 &&
        isRefValue(groups[0]) &&
        groups[0].$ref.kind === 'property_group' &&
        groups[0].$ref.key === plan.resource.key
    const groupId = resourceId('property_group', plan.resource.key)
    // A group only this event links is written inline; one other definitions also use stays its own.
    const inline = own && context.referrers.get(groupId) === 1 ? context.plans.get(groupId) : undefined
    const props = inline ? propsText(inline.resource.body) : undefined
    const fields: [string, string][] = objectFields(body, context, ['name', 'property_groups', 'enforcement_mode'])
    if (typeof body.enforcement_mode === 'string') {
        fields.push([props ? 'enforcement' : 'enforcement_mode', quoteString(body.enforcement_mode)])
    }
    if (props && inline) {
        inline.inline = true
        context.uses.add('prop')
        fields.push(['properties', props])
    } else if (body.property_groups !== undefined) {
        fields.push(['property_groups', render(body.property_groups, context, '    ')])
    }
    context.uses.add('event')
    return `event(${quoteString(plan.resource.key)}, ${fieldsText(fields, '')})`
}

// An insight's `dashboards` without the dashboards whose tiles show it: evaluation adds those back.
function ownDashboards(plan: Planned, context: Context): JsonValue[] | undefined {
    const listed = plan.resource.body.dashboards
    if (!Array.isArray(listed)) {
        return undefined
    }
    return listed.filter((item) => {
        if (!isRefValue(item) || item.$ref.kind !== 'dashboard') {
            return true
        }
        const board = context.plans.get(resourceId('dashboard', item.$ref.key))?.resource.body
        const tiles = Array.isArray(board?.tiles) ? board.tiles : []
        return !tiles.some((tile) => {
            const shown = (tile as JsonObject | null)?.insight
            return (
                isRefValue(shown) &&
                shown.$ref.kind === 'insight' &&
                shown.$ref.key === plan.resource.key &&
                !shown.$ref.attr
            )
        })
    })
}

const INSIGHT_FIELDS = ['name', 'description', 'tags', 'favorited', 'dashboards']

// The fields `trend` and `funnel` type, from the query wrappers' inputs. A source with anything else,
// a null, or a series kind those inputs don't take, keeps the long form, so the file type-checks.
const BUILDER_FIELDS = {
    TrendsQuery: [
        'kind',
        'aggregation_group_type_index',
        'breakdownFilter',
        'compareFilter',
        'dateRange',
        'filterTestAccounts',
        'interval',
        'properties',
        'series',
        'trendsFilter',
    ],
    FunnelsQuery: [
        'kind',
        'aggregation_group_type_index',
        'breakdownFilter',
        'dateRange',
        'filterTestAccounts',
        'funnelsFilter',
        'interval',
        'properties',
        'series',
    ],
}
const BUILDER_SERIES = ['EventsNode', 'ActionsNode']

function hasNull(value: JsonValue): boolean {
    if (value === null) {
        return true
    }
    if (Array.isArray(value)) {
        return value.some(hasNull)
    }
    return typeof value === 'object' && Object.values(value).some(hasNull)
}

function fitsBuilder(source: JsonObject): boolean {
    const fields = BUILDER_FIELDS[source.kind as keyof typeof BUILDER_FIELDS] as readonly string[]
    return (
        Object.keys(source).every((name) => fields.includes(name)) &&
        !hasNull(source) &&
        // Shapes PostHog's query schema allows and the builders' inputs don't: a property group, and
        // a breakdown without its list.
        (source.properties === undefined || Array.isArray(source.properties)) &&
        (source.breakdownFilter === undefined ||
            Array.isArray((source.breakdownFilter as JsonObject | null)?.breakdowns)) &&
        (source.series as JsonValue[]).every((node) => {
            const kind = (node as JsonObject | null)?.kind
            return kind === undefined || BUILDER_SERIES.includes(kind as string)
        })
    )
}

function insightText(plan: Planned, context: Context): string {
    const { body } = plan.resource
    const dashboards = ownDashboards(plan, context)
    const meta: [string, string][] = INSIGHT_FIELDS.filter(
        (name) => name !== 'dashboards' && body[name] !== undefined
    ).map((name) => [name, render(body[name], context, '    ')])
    if (dashboards && dashboards.length > 0) {
        meta.push(['dashboards', render(dashboards, context, '    ')])
    } else if (body.dashboards !== undefined && !Array.isArray(body.dashboards)) {
        meta.push(['dashboards', render(body.dashboards, context, '    ')])
    }
    const extra = Object.keys(body).filter((name) => !INSIGHT_FIELDS.includes(name) && name !== 'query')
    const query = body.query
    context.uses.add('insight')
    const isObject = (value: JsonValue | undefined): value is JsonObject =>
        typeof value === 'object' && value !== null && !Array.isArray(value)
    if (extra.length === 0 && isObject(query)) {
        const source = query.source
        const queryKeys = Object.keys(query).filter((name) => name !== 'kind' && name !== 'source')
        if (
            query.kind === 'DataVisualizationNode' &&
            isObject(source) &&
            source.kind === 'HogQLQuery' &&
            typeof source.query === 'string' &&
            Object.keys(source).length === 2 &&
            queryKeys.every((name) => ['display', 'chartSettings', 'tableSettings'].includes(name))
        ) {
            context.uses.add('hogql')
            const fields: [string, string][] = [
                ...meta,
                ['query', sqlWithDependencies(source.query, context) ?? quoteString(source.query)],
                ...queryKeys.map((name): [string, string] => [name, render(query[name], context, '    ')]),
            ]
            return `insight(${quoteString(plan.resource.key)}, hogql(${fieldsText(fields, '')}))`
        }
        if (
            query.kind === 'InsightVizNode' &&
            queryKeys.length === 0 &&
            isObject(source) &&
            (source.kind === 'TrendsQuery' || source.kind === 'FunnelsQuery') &&
            Array.isArray(source.series) &&
            fitsBuilder(source)
        ) {
            const funnel = source.kind === 'FunnelsQuery'
            context.uses.add(funnel ? 'funnel' : 'trend')
            const nodeFields = Object.entries(source)
                .filter(([name]) => name !== 'kind')
                .map(([name, value]): [string, string] => [
                    funnel && name === 'series' ? 'steps' : name,
                    render(value, context, '    '),
                ])
            return `insight(${quoteString(plan.resource.key)}, ${funnel ? 'funnel' : 'trend'}(${fieldsText([...meta, ...nodeFields], '')}))`
        }
    }
    const fields: [string, string][] = [
        ...meta,
        ...Object.entries(body)
            .filter(([name]) => !INSIGHT_FIELDS.includes(name))
            .map(([name, value]): [string, string] => [name, render(value, context, '    ')]),
    ]
    return `insight(${quoteString(plan.resource.key)}, ${fieldsText(fields, '')})`
}

// Variants and payloads become the builder's own options, which `filters` may not carry. The rest
// of `filters` stays as written, or becomes `rollout` when it is one condition for everyone.
function flagText(plan: Planned, context: Context): string {
    const { body } = plan.resource
    const filters = body.filters
    const fields = objectFields(body, context, ['key', 'filters'])
    const isObject = (value: JsonValue | undefined): value is JsonObject =>
        typeof value === 'object' && value !== null && !Array.isArray(value)
    if (!isObject(filters)) {
        if (filters !== undefined) {
            fields.push(['filters', render(filters, context, '    ')])
        }
        context.uses.add('flag')
        return `flag(${quoteString(plan.resource.key)}, ${fieldsText(fields, '')})`
    }
    const { groups, multivariate, payloads, ...rest } = filters
    const variants =
        isObject(multivariate) && Object.keys(multivariate).length === 1 && Array.isArray(multivariate.variants)
            ? multivariate.variants
            : undefined
    const variantsMovable =
        multivariate === undefined ||
        multivariate === null ||
        (variants !== undefined &&
            variants.length > 0 &&
            variants.every(
                (variant) =>
                    isObject(variant) &&
                    typeof variant.key === 'string' &&
                    typeof variant.rollout_percentage === 'number' &&
                    Object.keys(variant).every((name) => ['key', 'rollout_percentage', 'name'].includes(name))
            ))
    const payloadsMovable =
        payloads === undefined ||
        (isObject(payloads) && Object.values(payloads).every((value) => typeof value === 'string'))
    if (!variantsMovable || !payloadsMovable) {
        // A shape the options can't write keeps the API's own form, for check to report.
        fields.push(['filters', render(filters, context, '    ')])
        context.uses.add('flag')
        return `flag(${quoteString(plan.resource.key)}, ${fieldsText(fields, '')})`
    }
    const only = Array.isArray(groups) && groups.length === 1 ? groups[0] : undefined
    const simpleRollout =
        isObject(only) &&
        Object.keys(only).length === 2 &&
        Array.isArray(only.properties) &&
        only.properties.length === 0 &&
        typeof only.rollout_percentage === 'number'
    if (simpleRollout) {
        fields.push(['rollout', String((only as JsonObject).rollout_percentage)])
    }
    const remaining: JsonObject = {
        ...rest,
        ...(groups !== undefined && !simpleRollout ? { groups } : {}),
        ...(multivariate === null ? { multivariate: null } : {}),
    }
    // `filters: {}` is kept only when nothing else would make the builder write `filters`.
    if (Object.keys(remaining).length > 0 || Object.keys(filters).length === 0) {
        fields.push(['filters', render(remaining, context, '    ')])
    }
    if (variants !== undefined) {
        const plain = variants.every((variant) => Object.keys(variant as JsonObject).length === 2)
        fields.push([
            'variants',
            plain
                ? `{ ${variants.map((variant) => `${quoteKey((variant as JsonObject).key as string)}: ${(variant as JsonObject).rollout_percentage}`).join(', ')} }`
                : render(variants, context, '    '),
        ])
    }
    if (payloads !== undefined) {
        fields.push(['payloads', render(payloads, context, '    ')])
    }
    context.uses.add('flag')
    return `flag(${quoteString(plan.resource.key)}, ${fieldsText(fields, '')})`
}

function modelText(plan: Planned, context: Context): string {
    const { body } = plan.resource
    const skip = ['name', 'query', 'is_materialized', 'sync_frequency']
    const fields = objectFields(body, context, skip)
    if (body.is_materialized === true && typeof body.sync_frequency === 'string' && body.sync_frequency !== 'never') {
        fields.push(['materialize', quoteString(body.sync_frequency)])
    } else {
        for (const name of ['is_materialized', 'sync_frequency']) {
            if (body[name] !== undefined) {
                fields.push([name, render(body[name], context, '    ')])
            }
        }
    }
    if (isHogQLNode(body.query)) {
        context.uses.add('sql')
        fields.push(['query', sqlWithDependencies(body.query.query, context) ?? sqlText(body.query.query)])
    } else {
        fields.push(['query', render(body.query, context, '    ')])
    }
    if (body.columns === undefined) {
        fields.push(['columns', '{}'])
    }
    context.uses.add('model')
    return `model(${quoteString(plan.resource.key)}, ${fieldsText(fields, '')})`
}

function endpointText(plan: Planned, context: Context): string {
    const { body } = plan.resource
    const fields = objectFields(body, context, ['name', 'query'])
    if (isHogQLNode(body.query)) {
        context.uses.add('sql')
        fields.push(['query', sqlWithDependencies(body.query.query, context) ?? sqlText(body.query.query)])
    } else {
        fields.push(['query', render(body.query ?? null, context, '    ')])
    }
    context.uses.add('endpoint')
    return `endpoint(${quoteString(plan.resource.key)}, ${fieldsText(fields, '')})`
}

function metricText(plan: Planned, context: Context): string {
    const { body } = plan.resource
    const fields = objectFields(body, context, ['name', 'definition'])
    if (body.definition !== undefined) {
        const query = isHogQLNode(body.definition) ? sqlWithDependencies(body.definition.query, context) : undefined
        fields.push(['definition', query ?? render(body.definition, context, '    ')])
    }
    context.uses.add('metric')
    return `metric(${quoteString(plan.resource.key)}, ${fieldsText(fields, '')})`
}

// An experiment given its flag's definition depends on the flag, which a key alone does not say.
function experimentText(plan: Planned, context: Context): string {
    const { body } = plan.resource
    const flagKey = body.feature_flag_key
    const id = typeof flagKey === 'string' ? resourceId('flag', flagKey) : undefined
    const dependsOnFlag =
        id !== undefined &&
        (plan.resource.depends_on ?? []).some((entry) => resourceId(entry.kind, entry.key) === id) &&
        context.plans.has(id) &&
        !context.deferred.has(id)
    const fields = objectFields(body, context, dependsOnFlag ? ['feature_flag_key'] : [])
    if (dependsOnFlag) {
        fields.push(['feature_flag_key', refText({ $ref: { kind: 'flag', key: flagKey as string } }, context)])
    }
    context.uses.add('experiment')
    return `experiment(${quoteString(plan.resource.key)}, ${fieldsText(fields, '')})`
}

function checkText(plan: Planned, context: Context): string {
    const { body } = plan.resource
    const subject = body.subject_uuid
    const local =
        isRefValue(subject) &&
        subject.$ref.kind === 'model' &&
        !subject.$ref.attr &&
        body.subject_type === 'view' &&
        context.plans.has(resourceId('model', subject.$ref.key))
    const fields = objectFields(body, context, local ? ['subject_type', 'subject_uuid'] : [])
    if (local) {
        fields.push(['subject', render(subject, context, '    ')])
    }
    context.uses.add('check')
    return `check(${quoteString(plan.resource.key)}, ${fieldsText(fields, '')})`
}

function contextText(plan: Planned, context: Context, files: GeneratedFile[]): string {
    const { body } = plan.resource
    if (typeof body.content === 'string' && Object.keys(body).length === 2 && body.path === plan.resource.key) {
        const page = `context/${plan.resource.key}`
        files.push({ path: page, contents: body.content })
        context.uses.add('contextPage')
        context.uses.add('file')
        return `contextPage(${quoteString(plan.resource.key)}, { content: file(${quoteString(`./${page}`)}) })`
    }
    context.uses.add('contextPage')
    return `contextPage(${quoteString(plan.resource.key)}, ${render({ content: body.content ?? null }, context, '')})`
}

const LONG_FORMS: Readonly<Record<string, { fn: string; skip: readonly string[] }>> = {
    property_group: { fn: 'propertyGroup', skip: ['name'] },
    cohort: { fn: 'cohort', skip: [] },
    action: { fn: 'action', skip: [] },
    source: { fn: 'source', skip: [] },
    survey: { fn: 'survey', skip: [] },
    dashboard: { fn: 'dashboard', skip: [] },
    alert: { fn: 'alert', skip: [] },
    destination: { fn: 'destination', skip: [] },
}

function definitionText(plan: Planned, context: Context, files: GeneratedFile[]): string {
    switch (plan.resource.kind) {
        case 'event':
            return eventText(plan, context)
        case 'insight':
            return insightText(plan, context)
        case 'flag':
            return flagText(plan, context)
        case 'model':
            return modelText(plan, context)
        case 'endpoint':
            return endpointText(plan, context)
        case 'check':
            return checkText(plan, context)
        case 'metric':
            return metricText(plan, context)
        case 'experiment':
            return experimentText(plan, context)
        case 'context_page':
            return contextText(plan, context, files)
    }
    const form = LONG_FORMS[plan.resource.kind]
    if (!form) {
        throw new Error(`generateDefinitions has no definition form for the kind ${plan.resource.kind}.`)
    }
    context.uses.add(form.fn)
    return `${form.fn}(${quoteString(plan.resource.key)}, ${fieldsText(objectFields(plan.resource.body, context, form.skip), '')})`
}

function refsOf(value: JsonValue | undefined, into: string[]): void {
    if (isRefValue(value)) {
        into.push(resourceId(value.$ref.kind, value.$ref.key))
    } else if (Array.isArray(value)) {
        value.forEach((item) => refsOf(item, into))
    } else if (value !== null && typeof value === 'object') {
        Object.values(value).forEach((item) => refsOf(item, into))
    }
}

// Writes `define` calls that evaluate back to these resources: one file per family of kinds and an
// index.ts that exports them. The same resources always give the same bytes.
export function generateDefinitions(
    resources: readonly ResourceDescription[],
    options: GenerateOptions = {}
): GeneratedFile[] {
    const existing = new Set(options.existingKeys ?? [])
    const sorted = [...resources]
        .filter((resource) => !existing.has(resourceId(resource.kind, resource.key)))
        .sort(compareResources)
    const plans = new Map<string, Planned>()
    const taken = new Set<string>()
    for (const resource of sorted) {
        const family = FAMILIES[resource.kind]
        if (!family) {
            throw new Error(`generateDefinitions has no file for the kind ${resource.kind}.`)
        }
        let name = camel(resource.key)
        if (taken.has(name)) {
            name = `${name}${camel(resource.kind).replace(/^./, (char) => char.toUpperCase())}`
        }
        for (let suffix = 2; taken.has(name); suffix += 1) {
            name = `${camel(resource.key)}${suffix}`
        }
        taken.add(name)
        plans.set(resourceId(resource.kind, resource.key), { resource, name, family })
    }

    // Definitions in an order where each one's refs come first. A ref that closes a loop, or that
    // would make two files import each other, is written as ref(kind, key).
    const order: Planned[] = []
    const deferredBy = new Map<string, Set<string>>()
    const placed = new Set<string>()
    const visiting = new Set<string>()
    const fileEdges = new Map<string, Set<string>>()
    const reaches = (from: string, to: string, seen = new Set<string>()): boolean => {
        if (from === to) {
            return true
        }
        seen.add(from)
        return [...(fileEdges.get(from) ?? [])].some((next) => !seen.has(next) && reaches(next, to, seen))
    }
    const place = (id: string): void => {
        const plan = plans.get(id) as Planned
        visiting.add(id)
        const deferred = new Set<string>()
        const targets: string[] = []
        refsOf(plan.resource.body, targets)
        // A dependency is written by using its definition, so it is placed first like a ref.
        targets.push(...(plan.resource.depends_on ?? []).map((entry) => resourceId(entry.kind, entry.key)))
        for (const target of [...new Set(targets)].sort()) {
            const other = plans.get(target)
            if (!other) {
                continue
            }
            if (visiting.has(target)) {
                deferred.add(target)
                continue
            }
            if (other.family !== plan.family && reaches(other.family, plan.family)) {
                deferred.add(target)
                continue
            }
            if (!placed.has(target)) {
                place(target)
            }
            if (other.family !== plan.family) {
                const edges = fileEdges.get(plan.family) ?? new Set<string>()
                edges.add(other.family)
                fileEdges.set(plan.family, edges)
            }
        }
        deferredBy.set(id, deferred)
        visiting.delete(id)
        placed.add(id)
        order.push(plan)
    }
    for (const id of plans.keys()) {
        if (!placed.has(id)) {
            place(id)
        }
    }

    const referrers = new Map<string, number>()
    for (const plan of plans.values()) {
        const targets: string[] = []
        refsOf(plan.resource.body, targets)
        for (const target of new Set(targets)) {
            referrers.set(target, (referrers.get(target) ?? 0) + 1)
        }
    }
    const files: GeneratedFile[] = []
    const extraFiles: GeneratedFile[] = []
    const families = FAMILY_ORDER.filter((family) => order.some((plan) => plan.family === family))
    // Events first, so each event's inline group is known before the group itself would be written.
    const texts = new Map<Planned, { text: string; context: Context }>()
    for (const plan of [...order].sort(
        (a, b) => (a.resource.kind === 'event' ? -1 : 0) - (b.resource.kind === 'event' ? -1 : 0)
    )) {
        const context: Context = {
            plans,
            current: plan,
            imports: new Map(),
            uses: new Set(),
            deferred: deferredBy.get(resourceId(plan.resource.kind, plan.resource.key)) ?? new Set(),
            referrers,
        }
        texts.set(plan, { text: definitionText(plan, context, extraFiles), context })
    }
    for (const family of families) {
        const members = order.filter((plan) => plan.family === family && !plan.inline)
        if (members.length === 0) {
            continue
        }
        const uses = new Set<string>()
        const imports = new Map<string, Set<string>>()
        const blocks: string[] = []
        for (const plan of members) {
            const { text, context } = texts.get(plan) as { text: string; context: Context }
            context.uses.forEach((use) => uses.add(use))
            for (const [from, names] of context.imports) {
                const into = imports.get(from) ?? new Set<string>()
                names.forEach((name) => {
                    const target = [...plans.values()].find((candidate) => candidate.name === name)
                    // An inline group is written by its event, so importing its event would be wrong;
                    // groups that are written inline are never referenced across files.
                    if (!target?.inline) {
                        into.add(name)
                    }
                })
                imports.set(from, into)
            }
            blocks.push(`export const ${plan.name} = ${text}\n`)
        }
        const header = [`import { ${[...uses].sort().join(', ')} } from '@posthog/sdk/define'\n`]
        const local = [...imports.entries()]
            .filter(([, names]) => names.size > 0)
            .sort(([a], [b]) => (a < b ? -1 : 1))
            .map(([from, names]) => `import { ${[...names].sort().join(', ')} } from './${from}'\n`)
        if (local.length > 0) {
            header.push('\n', ...local)
        }
        files.push({ path: `${family}.ts`, contents: `${header.join('')}\n${blocks.join('\n')}` })
    }
    files.push({
        path: 'index.ts',
        contents: families
            .filter((family) => files.some((generated) => generated.path === `${family}.ts`))
            .sort()
            .map((family) => `export * from './${family}'\n`)
            .join(''),
    })
    return [...files, ...extraFiles].sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0))
}
