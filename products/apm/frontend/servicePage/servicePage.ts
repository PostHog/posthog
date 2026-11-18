import { FilterLogicalOperator, PropertyFilterType, PropertyGroupFilter, PropertyOperator } from '~/types'

/** The env, version and operation the service page is narrowed to. Null means "all". */
export interface ServiceScope {
    environment: string | null
    version: string | null
    operation: string | null
}

export const EMPTY_SERVICE_SCOPE: ServiceScope = { environment: null, version: null, operation: null }

// Where SDKs put the environment, newest spelling first. `deployment.environment` was renamed to
// `deployment.environment.name` in semconv 1.27, and `env` is what tag-style ingest paths write.
export const ENVIRONMENT_KEYS = ['deployment.environment.name', 'deployment.environment', 'env'] as const
export const VERSION_KEY = 'service.version'

// An empty string scopes to spans that set no environment, which the health API lists as null.
export function environmentLabel(environment: string): string {
    return environment === '' ? '(no environment)' : environment
}

/**
 * How a scope value goes into the URL. The router reads `1.0` back as the number 1 and `true` as a
 * boolean, so a value that looks like either goes in as a one-item list, which it keeps as written.
 * `urls.tracingService` in the manifest repeats this, since its source is copied into a generated file.
 */
export function scopeParamValue(value: string): string | string[] {
    return /^(true|false)$/i.test(value) || (value.trim() !== '' && !Number.isNaN(Number(value))) ? [value] : value
}

/** Reads a value written by `scopeParamValue`. */
export function readScopeParam(value: unknown): string | null {
    if (Array.isArray(value)) {
        return value.length > 0 ? String(value[0]) : null
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
        return String(value)
    }
    return typeof value === 'string' && value !== '' ? value : null
}

/** Like `readScopeParam`, but keeps `environment=` as the empty string, the unset environment. */
export function readEnvironmentParam(value: unknown): string | null {
    return value === '' ? '' : readScopeParam(value)
}

/** A flat span filter, the shape the span endpoints accept for `filterGroup`. */
export interface ServiceSpanFilter {
    key: string
    type: PropertyFilterType.Span | PropertyFilterType.SpanAttribute | PropertyFilterType.SpanResourceAttribute
    operator: PropertyOperator.Exact
    value: (string | number)[]
}

/**
 * The flat filters for a scope. `envKey` is the resource attribute the picked environment lives
 * under, or null when no span carries it as written (such as the unset environment). Pass `includeOperation: false` for views that list every operation, so the table
 * of endpoints doesn't collapse to the one picked in the operation selector.
 */
export function serviceScopeFilters(
    scope: ServiceScope,
    envKey: string | null,
    { includeOperation = true }: { includeOperation?: boolean } = {}
): ServiceSpanFilter[] {
    const filters: ServiceSpanFilter[] = []
    if (scope.environment && envKey) {
        filters.push({
            key: envKey,
            type: PropertyFilterType.SpanResourceAttribute,
            operator: PropertyOperator.Exact,
            value: [scope.environment],
        })
    }
    if (scope.version) {
        filters.push({
            key: VERSION_KEY,
            type: PropertyFilterType.SpanResourceAttribute,
            operator: PropertyOperator.Exact,
            value: [scope.version],
        })
    }
    if (includeOperation && scope.operation) {
        filters.push({
            key: 'name',
            type: PropertyFilterType.Span,
            operator: PropertyOperator.Exact,
            value: [scope.operation],
        })
    }
    return filters
}

/** The nested group the older `api.tracing` calls and the tracing scene's URL take. */
export function toPropertyGroupFilter(filters: ServiceSpanFilter[]): PropertyGroupFilter | undefined {
    if (filters.length === 0) {
        return undefined
    }
    return {
        type: FilterLogicalOperator.And,
        values: [
            { type: FilterLogicalOperator.And, values: filters as PropertyGroupFilter['values'][number]['values'] },
        ],
    }
}

export interface EnvironmentValues {
    key: string
    values: string[]
}

/**
 * The resource attribute the environment lives under, so span filters use the spelling the team
 * emits. Null when no key carries it, which is how the health API reports spans without one.
 */
export function environmentKeyFor(environment: string | null, candidates: EnvironmentValues[]): string | null {
    if (!environment) {
        return null
    }
    return candidates.find((candidate) => candidate.values.includes(environment))?.key ?? null
}
