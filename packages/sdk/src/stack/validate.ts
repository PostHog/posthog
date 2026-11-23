import type { JsonObject, JsonValue } from '../types.js'
import {
    compareResources,
    formatPath,
    isRefValue,
    pathPattern,
    type ResourceDependency,
    type ResourceDescription,
    type StackDescription,
    type StackProblem,
} from './description.js'
import { type ResourceOrigin, resourceId } from './evaluate.js'
import {
    type IdType,
    KEY_MAX_LENGTH,
    KEY_PATTERN,
    KEY_RULE,
    kindSpec,
    type KindSpec,
    type RefPosition,
    TILE_TOOL,
    wikiTitle,
} from './registry.js'
import { tileIssues } from './tiles.js'

// The part of the MCP tool library `check` uses: `createApiToolLibrary()` from
// `@posthog/mcp/dist/cli-library.mjs`, or `hog`'s `runtime.loadApiTools()`.
export interface SchemaValidator {
    validate(
        tool: string,
        input: Record<string, unknown>
    ):
        | { valid: true; input?: Record<string, unknown> }
        | { valid: false; error: string; issues?: { path: (string | number)[]; message: string }[] }
}

export interface StructureOptions {
    origins?: Map<string, ResourceOrigin>
    // `kind:key` of definitions evaluation left out on purpose; refs to them are not reported again.
    excluded?: ReadonlySet<string>
}

export interface ValidateOptions extends StructureOptions {
    validator: SchemaValidator
}

const PLACEHOLDERS: Record<IdType, JsonValue> = { number: 1, string: '00000000-0000-0000-0000-000000000000' }
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

interface Where {
    kind: string
    key: string
    file?: string
}

function whereOf(resource: ResourceDescription, options: StructureOptions): Where {
    const origin = options.origins?.get(resourceId(resource.kind, resource.key))
    const file = origin?.file ?? resource.source?.file
    return { kind: resource.kind, key: resource.key, ...(file ? { file } : {}) }
}

// Everything `check` can tell without running a kind's schema: keys, duplicates, references,
// cycles and the rules the registry states. `validateDescription` runs this and the schemas.
export function validateStructure(description: StackDescription, options: StructureOptions = {}): StackProblem[] {
    const index = new Map<string, ResourceDescription>()
    const problems: StackProblem[] = []
    for (const resource of description.resources) {
        const id = resourceId(resource.kind, resource.key)
        if (index.has(id)) {
            problems.push({
                code: 'key_duplicate',
                severity: 'error',
                ...whereOf(resource, options),
                message: `The description holds two ${resource.kind} resources with the key ${resource.key}. Each definition needs its own key.`,
            })
            continue
        }
        index.set(id, resource)
    }
    for (const resource of index.values()) {
        const where = whereOf(resource, options)
        const spec = kindSpec(resource.kind)
        if (!spec) {
            problems.push({
                code: 'kind_unknown',
                severity: 'error',
                ...where,
                message: `This version of check doesn't know the kind ${resource.kind}. Upgrade hog, or remove the definition.`,
            })
            continue
        }
        const origin = options.origins?.get(resourceId(resource.kind, resource.key))
        problems.push(...keyProblems(spec, resource, where, origin))
        problems.push(...omittedProblems(spec, resource, where))
        problems.push(...refProblems(spec, resource, index, where, options.excluded))
        problems.push(...dependencyProblems(resource, index, where))
        for (const issue of spec.rules?.(resource.body) ?? []) {
            problems.push({
                code: issue.code ?? 'rule_failed',
                severity: issue.severity ?? 'error',
                ...where,
                ...(issue.path ? { path: issue.path } : {}),
                message: issue.message,
            })
        }
        if (spec.composed?.includes('tiles')) {
            problems.push(
                ...tileIssues(resource.body.tiles).map(({ severity = 'error', ...issue }) => ({
                    severity,
                    ...where,
                    ...issue,
                }))
            )
        }
    }
    problems.push(...cycleProblems(index, options))
    problems.push(...wikiTitleProblems(index, options))
    if (description.resources.length === 0) {
        problems.push({
            code: 'stack_empty',
            severity: 'warning',
            message: 'The stack exports no definitions, so a push would remove everything it made before.',
        })
    }
    return problems
}

// The structure checks, and each resource's body against its kind's schema.
export function validateDescription(description: StackDescription, options: ValidateOptions): StackProblem[] {
    const problems = validateStructure(description, options)
    const index = new Map(description.resources.map((resource) => [resourceId(resource.kind, resource.key), resource]))
    for (const resource of index.values()) {
        const spec = kindSpec(resource.kind)
        if (spec) {
            problems.push(...schemaProblems(spec, resource, whereOf(resource, options), options.validator))
        }
    }
    return problems
}

function keyProblems(
    spec: KindSpec,
    resource: ResourceDescription,
    where: Where,
    origin: ResourceOrigin | undefined
): StackProblem[] {
    const { key } = resource
    if (origin?.dashboard !== undefined && key === '') {
        return [
            {
                code: 'key_invalid',
                severity: 'error',
                ...where,
                message: `Tile ${origin.tile} of dashboard ${origin.dashboard} makes an insight with no name and no tile key. Pass a key with tile(insight, { key }).`,
            },
        ]
    }
    const natural = spec.naturalKey
    const problems: StackProblem[] = []
    const fail = (reason: string): void => {
        problems.push({
            code: 'key_invalid',
            severity: 'error',
            ...where,
            message: `The ${spec.label} key "${key}" ${reason}.`,
        })
    }
    // Code points, as the API counts a name's length.
    const length = [...key].length
    const maxLength = natural?.maxLength ?? KEY_MAX_LENGTH
    if (length > maxLength) {
        fail(`is ${length} characters long, and a key has at most ${maxLength}`)
    } else if (!(natural ? new RegExp(natural.pattern, 'u') : KEY_PATTERN).test(key)) {
        fail(`can only use ${natural?.rule ?? KEY_RULE}`)
    } else if (
        natural?.reserved?.includes(key) ||
        natural?.reservedPrefixes?.some((prefix) => key.startsWith(prefix))
    ) {
        fail(`is a name PostHog reserves for its own ${spec.label}s. Choose another name`)
    }
    if (natural && resource.body[natural.field] !== key) {
        problems.push({
            code: 'key_mismatch',
            severity: 'error',
            ...where,
            path: natural.field,
            message: `A ${spec.label}'s key is its ${natural.field}, so ${natural.field} must be "${key}".`,
        })
    }
    return problems
}

function omittedProblems(spec: KindSpec, resource: ResourceDescription, where: Where): StackProblem[] {
    return (spec.omitted ?? [])
        .filter((name) => name in resource.body)
        .map((name) => ({
            code: 'field_not_allowed',
            severity: 'error' as const,
            ...where,
            path: name,
            message: `${name} is a step of a create call, not part of a ${spec.label}, so a definition can't set it.`,
        }))
}

interface FoundRef {
    path: string
    kind: string
    key: string
    attr: string
}

function findRefs(value: JsonValue, path: (string | number)[], into: FoundRef[]): void {
    if (isRefValue(value)) {
        into.push({ path: formatPath(path), kind: value.$ref.kind, key: value.$ref.key, attr: value.$ref.attr ?? 'id' })
        return
    }
    if (Array.isArray(value)) {
        value.forEach((item, index) => findRefs(item, [...path, index], into))
    } else if (value !== null && typeof value === 'object') {
        for (const [name, item] of Object.entries(value)) {
            findRefs(item, [...path, name], into)
        }
    }
}

// The values at a declared ref position, such as each item of `dashboards[]`, with their paths.
function valuesAt(body: JsonObject, pattern: string): { path: string; value: JsonValue }[] {
    let current: { path: string; value: JsonValue }[] = [{ path: '', value: body }]
    for (const segment of pattern.split('.')) {
        const many = segment.endsWith('[]')
        const name = many ? segment.slice(0, -2) : segment
        const next: { path: string; value: JsonValue }[] = []
        for (const { path, value } of current) {
            if (value === null || typeof value !== 'object' || Array.isArray(value) || !(name in value)) {
                continue
            }
            const child = value[name] as JsonValue
            const childPath = path ? `${path}.${name}` : name
            if (!many) {
                next.push({ path: childPath, value: child })
            } else if (Array.isArray(child)) {
                child.forEach((item, index) => next.push({ path: `${childPath}[${index}]`, value: item }))
            }
        }
        current = next
    }
    return current
}

function article(word: string): string {
    return /^[aeiou]/i.test(word) ? `an ${word}` : `a ${word}`
}

function positionText(position: RefPosition): string {
    return position.kinds.map(article).join(' or ')
}

function refProblems(
    spec: KindSpec,
    resource: ResourceDescription,
    index: Map<string, ResourceDescription>,
    where: Where,
    excluded: ReadonlySet<string> | undefined
): StackProblem[] {
    const problems: StackProblem[] = []
    const refs: FoundRef[] = []
    findRefs(resource.body, [], refs)
    const declared = new Map(spec.refs.map((position) => [position.path, position]))
    const free = spec.freeRefs ?? []
    for (const found of refs) {
        const position = declared.get(pathPattern(found.path))
        const fail = (code: string, message: string): void => {
            problems.push({ code, severity: 'error', ...where, path: found.path, message })
        }
        if (
            !position &&
            !free.some(
                (prefix) =>
                    found.path === prefix || found.path.startsWith(`${prefix}.`) || found.path.startsWith(`${prefix}[`)
            )
        ) {
            fail('reference_position', `${found.path} doesn't take a reference. Write the value itself.`)
            continue
        }
        if (position && !position.kinds.includes(found.kind)) {
            fail('reference_kind', `${found.path} takes ${positionText(position)}, not the ${found.kind} ${found.key}.`)
            continue
        }
        const attrs = kindSpec(found.kind)?.attrs
        const wanted = position?.attr ?? undefined
        if (wanted !== undefined ? found.attr !== wanted : attrs && !(found.attr in attrs)) {
            fail(
                'reference_attr',
                wanted !== undefined
                    ? `${found.path} takes the ${wanted} of ${positionText(position as RefPosition)}, and this ref reads its ${found.attr}.`
                    : `${found.path} reads ${found.attr} from the ${found.kind} ${found.key}, and ${article(found.kind)} has only ${Object.keys(attrs ?? {}).join(', ')}.`
            )
            continue
        }
        const id = resourceId(found.kind, found.key)
        if (!index.has(id) && !excluded?.has(id)) {
            fail(
                'reference_missing',
                `${found.path} refers to the ${found.kind} "${found.key}", which this stack doesn't define. Export it from the stack's index.ts, or fix the key.`
            )
        }
    }
    for (const position of spec.refs) {
        for (const { path, value } of valuesAt(resource.body, position.path)) {
            if (isRefValue(value) || (value === null && position.nullable)) {
                continue
            }
            if (position.literal === 'uuid' && typeof value === 'string' && UUID.test(value)) {
                continue
            }
            if (position.literal === 'string' && typeof value === 'string') {
                continue
            }
            if (position.literal === 'number' && typeof value === 'number' && Number.isInteger(value) && value > 0) {
                continue
            }
            problems.push({
                code: position.literal === 'uuid' ? 'subject_invalid' : 'reference_required',
                severity: 'error',
                ...where,
                path,
                message: position.literal
                    ? `${path} must be ${positionText(position)} in this stack, or the ${position.literal === 'uuid' ? 'UUID' : 'id'} of one this stack doesn't define.`
                    : `${path} must be ${position.kinds.map((kind) => `${article(kind)} definition`).join(' or ')}. A definition never holds an id PostHog assigned to an entity a stack manages.`,
            })
        }
    }
    return problems
}

function dependencyProblems(
    resource: ResourceDescription,
    index: Map<string, ResourceDescription>,
    where: Where
): StackProblem[] {
    const dependsOn: unknown = resource.depends_on
    if (dependsOn === undefined) {
        return []
    }
    const valid =
        Array.isArray(dependsOn) &&
        dependsOn.every(
            (entry) =>
                typeof entry === 'object' &&
                entry !== null &&
                typeof (entry as ResourceDependency).kind === 'string' &&
                typeof (entry as ResourceDependency).key === 'string'
        )
    if (!valid) {
        return [
            {
                code: 'dependency_invalid',
                severity: 'error',
                ...where,
                path: 'depends_on',
                message: 'depends_on must be a list of { kind, key } entries.',
            },
        ]
    }
    return (dependsOn as ResourceDependency[]).flatMap((entry, position) =>
        index.has(resourceId(entry.kind, entry.key))
            ? []
            : [
                  {
                      code: 'dependency_missing',
                      severity: 'error' as const,
                      ...where,
                      path: `depends_on[${position}]`,
                      message: `The ${resource.kind} ${resource.key} reads the ${entry.kind} ${entry.key}, which this stack doesn't define, so PostHog could not create it first. Export the ${entry.kind} from the stack's index.ts. If another stack defines it, write its name as text instead, such as sql.raw('${entry.key}').`,
                  },
              ]
    )
}

// The wiki refuses two pages whose first headings are the same once normalized. Pages already in
// the wiki count too, which check can't see.
function wikiTitleProblems(index: Map<string, ResourceDescription>, options: StructureOptions): StackProblem[] {
    const first = new Map<string, ResourceDescription>()
    const problems: StackProblem[] = []
    const pages = [...index.values()].filter((resource) => resource.kind === 'context_page').sort(compareResources)
    for (const page of pages) {
        const { path, content } = page.body
        if (
            typeof path !== 'string' ||
            typeof content !== 'string' ||
            path === 'AGENTS.md' ||
            path.endsWith('/index.md')
        ) {
            continue
        }
        const title = wikiTitle(content)
        if (!title) {
            continue
        }
        const earlier = first.get(title)
        if (!earlier) {
            first.set(title, page)
            continue
        }
        problems.push({
            code: 'context_page_refused',
            severity: 'error',
            ...whereOf(page, options),
            path: 'content',
            message: `The wiki refuses this page: its title duplicates the normalized title in ${earlier.key} ("${title}"). Give one of the pages a different first heading.`,
        })
    }
    return problems
}

// A cycle the engine could not order. A dashboard's tiles depend on their insights, and the
// insights list the dashboard back; the engine places tiles in a separate step, so that pair is not one.
function cycleProblems(index: Map<string, ResourceDescription>, options: StructureOptions): StackProblem[] {
    const edges = new Map<string, string[]>()
    // Edges that come from depends_on, by `from -> to`.
    const named = new Set<string>()
    for (const [id, resource] of index) {
        const refs: FoundRef[] = []
        findRefs(resource.body, [], refs)
        const composed = new Set(kindSpec(resource.kind)?.composed ?? [])
        const dependsOn = Array.isArray(resource.depends_on) ? resource.depends_on : []
        const fromDependsOn = dependsOn
            .filter((entry) => typeof entry?.kind === 'string' && typeof entry?.key === 'string')
            .map((entry) => resourceId(entry.kind, entry.key))
        fromDependsOn.forEach((target) => named.add(`${id} -> ${target}`))
        edges.set(id, [
            ...new Set(
                [
                    ...refs
                        .filter((ref) => !(composed.has('tiles') && ref.path.startsWith('tiles[')))
                        .map((ref) => resourceId(ref.kind, ref.key)),
                    ...fromDependsOn,
                ].filter((target) => index.has(target))
            ),
        ])
    }
    const problems: StackProblem[] = []
    const state = new Map<string, 'open' | 'done'>()
    const stack: string[] = []
    const reported = new Set<string>()
    const visit = (id: string): void => {
        state.set(id, 'open')
        stack.push(id)
        for (const next of edges.get(id) ?? []) {
            if (state.get(next) === 'open') {
                const cycle = stack.slice(stack.indexOf(next))
                const name = [...cycle].sort().join(' ')
                if (!reported.has(name)) {
                    reported.add(name)
                    const first = index.get([...cycle].sort()[0] as string) as ResourceDescription
                    const path = [...cycle, next]
                    const reads = path.slice(1).some((member, at) => named.has(`${path[at]} -> ${member}`))
                    problems.push({
                        code: reads ? 'dependency_cycle' : 'reference_cycle',
                        severity: 'error',
                        ...whereOf(first, options),
                        message: `These definitions ${reads ? 'depend on' : 'refer to'} each other in a loop, so none can be created first: ${path.map((member) => member.replace(':', ' ')).join(' -> ')}.`,
                    })
                }
            } else if (!state.has(next)) {
                visit(next)
            }
        }
        stack.pop()
        state.set(id, 'done')
    }
    for (const id of [...index.keys()].sort()) {
        if (!state.has(id)) {
            visit(id)
        }
    }
    return problems
}

// Each ref becomes a value of the type its target's field has, so the kind's schema sees a body
// shaped like the API's.
function withPlaceholders(value: JsonValue): JsonValue {
    if (isRefValue(value)) {
        const type = kindSpec(value.$ref.kind)?.attrs[value.$ref.attr ?? 'id'] ?? 'string'
        return PLACEHOLDERS[type]
    }
    if (Array.isArray(value)) {
        return value.map(withPlaceholders)
    }
    if (value !== null && typeof value === 'object') {
        if ('$secret' in value && typeof value.$secret === 'string') {
            return 'secret'
        }
        return Object.fromEntries(Object.entries(value).map(([name, item]) => [name, withPlaceholders(item)]))
    }
    return value
}

// The tool library joins every issue into one message. Older bundles give only that message.
const ISSUE_START = /; (?=parameter "|missing required parameter: )/
const ISSUE_PATH = /^(?:parameter "([^"]*)"|missing required parameter: ([^\s;(]+))/

interface SchemaIssue {
    path: (string | number)[]
    message: string
}

function issuesFrom(result: { error: string; issues?: SchemaIssue[] }): SchemaIssue[] {
    if (result.issues && result.issues.length > 0) {
        return result.issues
    }
    const text = result.error.replace(/^Invalid input for "[^"]*": /, '')
    return text.split(ISSUE_START).map((issue) => {
        const match = ISSUE_PATH.exec(issue)
        const raw = match?.[1] ?? match?.[2] ?? ''
        return {
            path: raw
                .split('.')
                .filter(Boolean)
                .map((part) => (/^\d+$/.test(part) ? Number(part) : part)),
            message: issue,
        }
    })
}

// Every key the author wrote that the schema dropped while parsing, recursively. The MCP schemas
// strip keys they don't know, so a misspelled field would otherwise vanish without a word.
function droppedKeys(
    supplied: JsonValue,
    parsed: unknown,
    path: (string | number)[],
    into: (string | number)[][]
): void {
    if (Array.isArray(supplied)) {
        if (Array.isArray(parsed) && parsed.length === supplied.length) {
            supplied.forEach((item, index) => droppedKeys(item, parsed[index], [...path, index], into))
        }
        return
    }
    if (
        supplied === null ||
        typeof supplied !== 'object' ||
        parsed === null ||
        typeof parsed !== 'object' ||
        Array.isArray(parsed)
    ) {
        return
    }
    for (const [name, value] of Object.entries(supplied)) {
        if (!(name in parsed)) {
            into.push([...path, name])
        } else {
            droppedKeys(value, (parsed as Record<string, unknown>)[name], [...path, name], into)
        }
    }
}

function valueAtPath(body: JsonValue, path: readonly (string | number)[]): JsonValue | undefined {
    let current: JsonValue | undefined = body
    for (const part of path) {
        if (current === null || typeof current !== 'object') {
            return undefined
        }
        current = (current as Record<string | number, JsonValue>)[part]
    }
    return current
}

// A body path a named gap of the kind covers: the path or one above it matches the gap, and the
// gap's condition, if any, holds for the value there.
function coveredByGap(spec: KindSpec, body: JsonObject, path: readonly (string | number)[]): boolean {
    return (spec.schemaGaps ?? []).some((gap) =>
        path.some((_, index) => {
            const prefix = path.slice(0, index + 1)
            return pathPattern(formatPath(prefix)) === gap.path && (!gap.when || gap.when(valueAtPath(body, prefix)))
        })
    )
}

function runSchema(
    validator: SchemaValidator,
    tool: string,
    input: JsonObject,
    where: Where,
    spec: KindSpec,
    toBody: (path: (string | number)[]) => (string | number)[],
    body: JsonObject
): StackProblem[] {
    let result: ReturnType<SchemaValidator['validate']>
    try {
        result = validator.validate(tool, input)
    } catch {
        return [
            {
                code: 'schema_unavailable',
                severity: 'warning',
                ...where,
                message: `The tool catalog has no ${tool} tool, so check could not validate this ${spec.label}'s fields. Upgrade hog.`,
            },
        ]
    }
    if (!result.valid) {
        return issuesFrom(result).flatMap(({ path, message }) => {
            if (coveredByGap(spec, body, toBody(path))) {
                return []
            }
            const bodyPath = formatPath(toBody(path))
            return [
                {
                    code: 'schema_invalid',
                    severity: 'error' as const,
                    ...where,
                    ...(bodyPath ? { path: bodyPath } : {}),
                    message: bodyPath ? `${bodyPath}: ${message}` : message,
                },
            ]
        })
    }
    const dropped: (string | number)[][] = []
    droppedKeys(input, result.input ?? input, [], dropped)
    return dropped
        .map(toBody)
        .filter((path) => !coveredByGap(spec, body, path))
        .map((path) => {
            const at = formatPath(path)
            const kept = (spec.keptAsWritten ?? []).some(
                (prefix) => at === prefix || at.startsWith(`${prefix}.`) || at.startsWith(`${prefix}[`)
            )
            if (kept) {
                return {
                    code: 'unknown_field',
                    severity: 'warning' as const,
                    ...where,
                    path: at,
                    message: `${at} is not a field check knows for this ${spec.label}. PostHog saves it as written, so check its spelling.`,
                }
            }
            return {
                code: 'unknown_field',
                severity: 'error' as const,
                ...where,
                path: at,
                message: `${at} is not a field the ${spec.label} schema knows, so PostHog would drop it. Remove it, or check its spelling.`,
            }
        })
}

function splitPath(path: string): (string | number)[] {
    return path
        .split(/\.|(?=\[)/)
        .filter(Boolean)
        .map((part) => (part.startsWith('[') ? Number(part.slice(1, -1)) : part))
}

function schemaProblems(
    spec: KindSpec,
    resource: ResourceDescription,
    where: Where,
    validator: SchemaValidator
): StackProblem[] {
    if (spec.toolPending) {
        return (spec.structural?.(resource.body) ?? []).map((issue) => ({
            code: 'schema_invalid',
            severity: 'error' as const,
            ...where,
            path: issue.path,
            message: issue.message,
        }))
    }
    const skipped = new Set([...(spec.composed ?? []), ...(spec.omitted ?? [])])
    const body: JsonObject = {}
    for (const [name, value] of Object.entries(resource.body)) {
        if (!skipped.has(name)) {
            body[name] = withPlaceholders(value)
        }
    }
    const adapted = spec.toInput?.(body)
    const problems = runSchema(
        validator,
        spec.tool,
        adapted?.input ?? body,
        where,
        spec,
        (path) => (adapted ? splitPath(adapted.bodyPath(formatPath(path))) : path),
        resource.body
    )
    for (const extra of spec.querySchemas?.(resource.body) ?? []) {
        if ('unchecked' in extra) {
            problems.push({
                code: 'query_unchecked',
                severity: 'warning',
                ...where,
                path: extra.path,
                message: extra.unchecked,
            })
            continue
        }
        problems.push(
            ...runSchema(
                validator,
                extra.tool,
                withPlaceholders(extra.input) as JsonObject,
                where,
                spec,
                (path) => [...extra.prefix, ...path],
                resource.body
            )
        )
    }
    for (const issue of spec.structural?.(resource.body) ?? []) {
        problems.push({ code: 'schema_invalid', severity: 'error', ...where, path: issue.path, message: issue.message })
    }
    if (spec.composed?.includes('tiles') && Array.isArray(resource.body.tiles)) {
        resource.body.tiles.forEach((tile, position) => {
            const text = (tile as JsonObject | null)?.text
            if (text === null || typeof text !== 'object' || Array.isArray(text)) {
                return
            }
            const input: JsonObject = { id: PLACEHOLDERS.number, type: 'text', body: (text as JsonObject).body ?? null }
            problems.push(
                ...runSchema(
                    validator,
                    TILE_TOOL,
                    input,
                    where,
                    spec,
                    (path) =>
                        path[0] === 'body' ? ['tiles', position, 'text', ...path] : ['tiles', position, ...path],
                    resource.body
                )
            )
        })
    }
    return problems
}
