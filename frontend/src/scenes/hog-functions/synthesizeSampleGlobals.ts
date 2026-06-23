import {
    AnyPropertyFilter,
    CyclotronJobFiltersType,
    CyclotronJobInputType,
    CyclotronJobInvocationGlobals,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

// Synthesizes a sample invocation globals object for the test panel without querying ClickHouse.
//
// The earlier implementation fetched a recent real event matching the configured filter via an
// `EventsQuery`. That blew the per-query memory limit on very high-volume teams (decompressing
// `properties` across a deep `timestamp DESC` scan), so testing was broken for the customers most
// likely to need it. We replace it with a deterministic, in-memory synthesis:
//
//   1. Start from the existing static example globals (the same object the test panel used to fall
//      back to when the fetch failed) so all the framing — project, source, url, person scaffolding
//      — keeps working.
//   2. Use the configured event filter to pick the event name and populate any property clauses we
//      can deterministically satisfy. The synthesized event is allowed to be imperfect (regex /
//      `is_not_set` / arbitrary HogQL clauses aren't enforced) — the goal is "the destination has
//      something realistic-looking to operate on", not exact filter passage. Users can refine via
//      the JSON editor for stricter cases.
//   3. Walk the configured `inputs` and surface every `{event.properties.X}`, `{person.properties.Y}`,
//      `{groups.<name>.properties.Z}` reference, ensuring each path has a placeholder value so the
//      destination template renders to something other than `undefined`.

const PLACEHOLDER_STRING = 'example'
const PLACEHOLDER_NUMBER = 1

export function synthesizeSampleGlobals({
    base,
    filters,
    inputs,
}: {
    base: CyclotronJobInvocationGlobals
    filters: CyclotronJobFiltersType | undefined | null
    inputs: Record<string, CyclotronJobInputType> | undefined | null
}): CyclotronJobInvocationGlobals {
    const globals: CyclotronJobInvocationGlobals = JSON.parse(JSON.stringify(base))
    globals.event.properties = globals.event.properties ?? {}
    if (globals.person) {
        globals.person.properties = globals.person.properties ?? {}
    }
    globals.groups = globals.groups ?? {}

    const firstEventId = filters?.events?.[0]?.id
    if (typeof firstEventId === 'string' && firstEventId.length > 0) {
        globals.event.event = firstEventId
    }

    applyPropertyFilters(globals, filters?.properties)
    for (const event of filters?.events ?? []) {
        applyPropertyFilters(globals, event.properties)
    }
    for (const action of filters?.actions ?? []) {
        applyPropertyFilters(globals, action.properties)
    }

    for (const path of collectReferencedPaths(inputs)) {
        ensurePathExists(globals, path)
    }

    return globals
}

function applyPropertyFilters(
    globals: CyclotronJobInvocationGlobals,
    propertyFilters: AnyPropertyFilter[] | undefined | null
): void {
    for (const filter of propertyFilters ?? []) {
        applyPropertyFilter(globals, filter)
    }
}

function applyPropertyFilter(globals: CyclotronJobInvocationGlobals, filter: AnyPropertyFilter): void {
    if (!('key' in filter) || typeof filter.key !== 'string' || filter.key.length === 0) {
        return
    }
    const target = propertyTarget(globals, filter)
    if (!target) {
        return
    }
    const operator = ('operator' in filter ? filter.operator : undefined) ?? PropertyOperator.Exact
    const value = 'value' in filter ? filter.value : undefined

    // Skip clauses that explicitly require the key to be absent. Anything not in the explicit set
    // below gets a best-effort assignment (just write the filter value, scalar or first array
    // element) so the destination at least sees the key.
    switch (operator) {
        case PropertyOperator.IsNotSet:
            return
        case PropertyOperator.IsSet:
            if (!(filter.key in target)) {
                target[filter.key] = PLACEHOLDER_STRING
            }
            return
        case PropertyOperator.IsNot:
        case PropertyOperator.NotIContains:
        case PropertyOperator.NotRegex:
        case PropertyOperator.NotIn:
        case PropertyOperator.NotIContainsMulti:
        case PropertyOperator.NotBetween:
        case PropertyOperator.SemverNeq:
            target[filter.key] = `not-${scalar(value) ?? PLACEHOLDER_STRING}`
            return
        case PropertyOperator.GreaterThan:
        case PropertyOperator.GreaterThanOrEqual:
        case PropertyOperator.Minimum: {
            const numeric = numericScalar(value)
            target[filter.key] = numeric != null ? numeric + 1 : PLACEHOLDER_NUMBER
            return
        }
        case PropertyOperator.LessThan:
        case PropertyOperator.LessThanOrEqual:
        case PropertyOperator.Maximum: {
            const numeric = numericScalar(value)
            target[filter.key] = numeric != null ? numeric - 1 : PLACEHOLDER_NUMBER
            return
        }
        case PropertyOperator.Between: {
            const [low, high] = arrayBounds(value)
            target[filter.key] = low != null && high != null ? (low + high) / 2 : PLACEHOLDER_NUMBER
            return
        }
        case PropertyOperator.In:
        case PropertyOperator.IContainsMulti: {
            const first = scalar(Array.isArray(value) ? value[0] : value)
            target[filter.key] = first ?? PLACEHOLDER_STRING
            return
        }
        case PropertyOperator.Regex:
            // Can't deterministically satisfy a regex; assigning the pattern string usually doesn't
            // match. Fall through to the best-effort assignment so at least the key is set.
            target[filter.key] = scalar(value) ?? PLACEHOLDER_STRING
            return
        default:
            target[filter.key] = scalar(Array.isArray(value) ? value[0] : value) ?? PLACEHOLDER_STRING
    }
}

function propertyTarget(globals: CyclotronJobInvocationGlobals, filter: AnyPropertyFilter): Record<string, any> | null {
    switch (filter.type) {
        case PropertyFilterType.Event:
        case PropertyFilterType.EventMetadata:
        case PropertyFilterType.Feature:
        case PropertyFilterType.Element:
            return globals.event.properties
        case PropertyFilterType.Person:
            if (!globals.person) {
                return null
            }
            return globals.person.properties
        case PropertyFilterType.Group: {
            const index = (filter as { group_type_index?: number | null }).group_type_index
            if (index == null) {
                return null
            }
            const groupEntry = Object.values(globals.groups ?? {}).find((g) => g.index === index)
            if (!groupEntry) {
                return null
            }
            groupEntry.properties = groupEntry.properties ?? {}
            return groupEntry.properties
        }
        default:
            return null
    }
}

function scalar(value: unknown): string | number | boolean | null | undefined {
    if (value == null) {
        return undefined
    }
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
        return value
    }
    return undefined
}

function numericScalar(value: unknown): number | null {
    if (typeof value === 'number' && Number.isFinite(value)) {
        return value
    }
    if (typeof value === 'string') {
        const parsed = Number(value)
        if (Number.isFinite(parsed)) {
            return parsed
        }
    }
    return null
}

function arrayBounds(value: unknown): [number | null, number | null] {
    if (!Array.isArray(value) || value.length < 2) {
        return [null, null]
    }
    return [numericScalar(value[0]), numericScalar(value[1])]
}

// Matches a hog/liquid templating reference like `{event.properties.foo}`, `{person.properties.bar}`,
// or `{groups.account.properties.plan}`. We only care about the dotted path inside the braces — any
// formatting or filters that come after a `|` we treat as out of scope (and not part of the path).
const REFERENCE_PATTERN = /\{([a-z_][a-z0-9_]*(?:\.[a-z_$][a-z0-9_$]*)+)/gi

export function collectReferencedPaths(inputs: Record<string, CyclotronJobInputType> | undefined | null): string[] {
    const paths = new Set<string>()
    if (!inputs) {
        return []
    }
    for (const input of Object.values(inputs)) {
        walkValueForReferences(input?.value, paths)
    }
    return [...paths]
}

function walkValueForReferences(value: unknown, paths: Set<string>): void {
    if (value == null) {
        return
    }
    if (typeof value === 'string') {
        for (const match of value.matchAll(REFERENCE_PATTERN)) {
            paths.add(match[1])
        }
        return
    }
    if (Array.isArray(value)) {
        for (const item of value) {
            walkValueForReferences(item, paths)
        }
        return
    }
    if (typeof value === 'object') {
        for (const item of Object.values(value as Record<string, unknown>)) {
            walkValueForReferences(item, paths)
        }
    }
}

// Roots we know how to populate in invocation globals. Any reference whose first segment isn't one
// of these (e.g. `inputs.foo`, `source.name`) is left alone — it either resolves via another part of
// the invocation context or is something the synthesizer can't meaningfully fill in.
const SUPPORTED_ROOTS = new Set(['event', 'person', 'groups'])

function ensurePathExists(globals: CyclotronJobInvocationGlobals, path: string): void {
    const segments = path.split('.')
    if (segments.length < 2 || !SUPPORTED_ROOTS.has(segments[0])) {
        return
    }
    let cursor: any = globals
    for (let i = 0; i < segments.length - 1; i++) {
        const segment = segments[i]
        const next = cursor[segment]
        if (next == null || typeof next !== 'object') {
            cursor[segment] = {}
        }
        cursor = cursor[segment]
    }
    const leaf = segments[segments.length - 1]
    if (cursor[leaf] === undefined) {
        cursor[leaf] = PLACEHOLDER_STRING
    }
}
