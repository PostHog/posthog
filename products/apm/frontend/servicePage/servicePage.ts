import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { FilterLogicalOperator, PropertyFilterType, PropertyGroupFilter, PropertyOperator } from '~/types'

import type { _TracingLatencyPercentilesRowApi } from 'products/tracing/frontend/generated/api.schemas'
import type { Span } from 'products/tracing/frontend/types'

/** The env, version and operation the service page is narrowed to. Null means "all". */
export interface ServiceScope {
    environment: string | null
    version: string | null
    operation: string | null
}

export const EMPTY_SERVICE_SCOPE: ServiceScope = { environment: null, version: null, operation: null }

// Where SDKs put the environment, newest spelling first. `deployment.environment` was renamed to
// `deployment.environment.name` in semconv 1.27, and `env` is what tag-style ingest paths write.
// Same keys and order as the health API's `ENVIRONMENT_ATTRIBUTES`, which falls back to the cluster name.
export const ENVIRONMENT_KEYS = [
    'deployment.environment.name',
    'deployment.environment',
    'env',
    'k8s.cluster.name',
] as const
export const VERSION_KEY = 'service.version'

// HTTP status lives under the current semconv key or the older one, depending on the SDK.
export const HTTP_STATUS_KEYS = ['http.response.status_code', 'http.status_code'] as const

// Where instrumentation records why a span failed, most specific first. Mirrors the order the
// backend trace summary reads them in.
const ERROR_MESSAGE_KEYS = ['exception.message', 'error.message', 'otel.status_description'] as const
const ERROR_TYPE_KEYS = ['exception.type', 'error.type'] as const

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
    operator: PropertyOperator.Exact | PropertyOperator.IsNotSet
    value?: (string | number)[]
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
    } else if (scope.environment === '') {
        // The unset environment is spans with none of the keys, so match those, not every span.
        for (const key of ENVIRONMENT_KEYS) {
            filters.push({ key, type: PropertyFilterType.SpanResourceAttribute, operator: PropertyOperator.IsNotSet })
        }
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

export const ERROR_STATUS_FILTER: ServiceSpanFilter = {
    key: 'status_code',
    type: PropertyFilterType.Span,
    operator: PropertyOperator.Exact,
    value: [2],
}

/**
 * Narrows the older status key's breakdown to spans without the current one, so a span that
 * carries both is counted once, under the current key.
 */
export const LEGACY_HTTP_STATUS_ONLY_FILTER: ServiceSpanFilter = {
    key: HTTP_STATUS_KEYS[0],
    type: PropertyFilterType.SpanAttribute,
    operator: PropertyOperator.IsNotSet,
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

export interface LatencyPercentiles {
    times: string[]
    p50: number[]
    p95: number[]
    p99: number[]
}

/** Per time bucket, in nanoseconds. A bucket with no spans is NaN, so the line breaks instead of dropping to zero. */
export function latencyPercentileSeries(rows: _TracingLatencyPercentilesRowApi[]): LatencyPercentiles {
    const values = (pick: (row: _TracingLatencyPercentilesRowApi) => number | null): number[] =>
        rows.map((row) => pick(row) ?? NaN)
    return {
        times: rows.map((row) => row.time),
        p50: values((row) => row.p50_ns),
        p95: values((row) => row.p95_ns),
        p99: values((row) => row.p99_ns),
    }
}

export interface SparklineRow {
    time: string
    count: number
}

export interface RequestsSeries {
    times: string[]
    requests: number[]
    errors: number[]
}

/**
 * Lines the error counts up against the request buckets. The two come from separate queries, and
 * the error query skips buckets with no errors, so a bucket missing there is zero errors.
 */
export function mergeRequestsSeries(requests: SparklineRow[], errors: SparklineRow[]): RequestsSeries {
    const byTime = new Map<string, { requests: number; errors: number }>()
    for (const row of requests) {
        const entry = byTime.get(row.time) ?? { requests: 0, errors: 0 }
        entry.requests += row.count
        byTime.set(row.time, entry)
    }
    for (const row of errors) {
        const entry = byTime.get(row.time) ?? { requests: 0, errors: 0 }
        entry.errors += row.count
        byTime.set(row.time, entry)
    }
    const times = [...byTime.keys()].sort()
    return {
        times,
        // A bucket's error spans are also in its requests, so the bars stack the OK part on top.
        requests: times.map((time) => Math.max(0, byTime.get(time)!.requests - byTime.get(time)!.errors)),
        errors: times.map((time) => byTime.get(time)!.errors),
    }
}

export function bucketIntervalLabel(times: string[]): string | null {
    if (times.length < 2) {
        return null
    }
    const seconds = Math.round((Date.parse(times[1]) - Date.parse(times[0])) / 1000)
    if (!Number.isFinite(seconds) || seconds <= 0) {
        return null
    }
    // Short plural forms keep the chart's y-axis label from truncating.
    const units: [number, string, string][] = [
        [86400, 'day', 'days'],
        [3600, 'hour', 'h'],
        [60, 'minute', 'min'],
        [1, 'second', 's'],
    ]
    for (const [size, singular, plural] of units) {
        if (seconds % size === 0) {
            const count = seconds / size
            return count === 1 ? singular : `${count} ${plural}`
        }
    }
    return null
}

export type ErrorGroupKind = 'message' | 'exception_type' | 'http_status' | 'span_name'

export const ERROR_GROUP_KIND_LABEL: Record<ErrorGroupKind, string> = {
    message: 'Message',
    exception_type: 'Exception type',
    http_status: 'HTTP status',
    span_name: 'Span name',
}

export interface SpanErrorGroup {
    kind: ErrorGroupKind
    value: string
}

export interface TopError extends SpanErrorGroup {
    /** Unique across kinds, so a status code and a message with the same text stay two rows. */
    key: string
    count: number
    lastSeen: string
    latest: Span
}

function firstValue(sources: (Record<string, string> | undefined)[], keys: readonly string[]): string | null {
    for (const key of keys) {
        for (const source of sources) {
            const value = source?.[key]
            if (value) {
                return value
            }
        }
    }
    return null
}

export function spanErrorGroup(span: Span): SpanErrorGroup {
    const sources = [...(span.events ?? []).map((event) => event.attributes), span.attributes]
    const message = firstValue(sources, ERROR_MESSAGE_KEYS)
    if (message) {
        return { kind: 'message', value: message }
    }
    const exceptionType = firstValue(sources, ERROR_TYPE_KEYS)
    if (exceptionType) {
        return { kind: 'exception_type', value: exceptionType }
    }
    const statusCode = firstValue([span.attributes], HTTP_STATUS_KEYS)
    if (statusCode) {
        return { kind: 'http_status', value: String(statusCode) }
    }
    return { kind: 'span_name', value: span.name }
}

export function topErrorGroups(spans: Span[], limit = 10): TopError[] {
    const groups = new Map<string, TopError>()
    for (const span of spans) {
        const group = spanErrorGroup(span)
        const key = `${group.kind}:${group.value}`
        const existing = groups.get(key)
        if (existing) {
            existing.count += 1
            continue
        }
        groups.set(key, { ...group, key, count: 1, lastSeen: span.timestamp, latest: span })
    }
    return [...groups.values()].sort((a, b) => b.count - a.count).slice(0, limit)
}

export interface StatusCodeErrors {
    statusCode: string
    errors: number
}

/**
 * Merges per-key status code breakdowns into one list of codes with errors, most errors first.
 * Each span must appear in only one breakdown, see `LEGACY_HTTP_STATUS_ONLY_FILTER`.
 */
export function mergeStatusCodeErrors(breakdowns: { value: string; error_count: number }[][]): StatusCodeErrors[] {
    const byCode = new Map<string, number>()
    for (const rows of breakdowns) {
        for (const row of rows) {
            if (!row.value || row.error_count <= 0) {
                continue
            }
            byCode.set(row.value, (byCode.get(row.value) ?? 0) + row.error_count)
        }
    }
    return [...byCode.entries()]
        .map(([statusCode, errors]) => ({ statusCode, errors }))
        .sort((a, b) => b.errors - a.errors)
}

/** The tracing viewer, showing this service's traces under the same scope and window. */
export function serviceTracesUrl(
    serviceName: string,
    dateRange: { date_from: string; date_to: null },
    filters: ServiceSpanFilter[],
    { errorsOnly = false }: { errorsOnly?: boolean } = {}
): string {
    const filterGroup = toPropertyGroupFilter(errorsOnly ? [...filters, ERROR_STATUS_FILTER] : filters)
    return combineUrl(urls.tracing(), {
        // A list, not a string: the viewer splits a string on commas.
        serviceNames: [serviceName],
        dateRange: JSON.stringify(dateRange),
        ...(filterGroup ? { filterGroup: JSON.stringify(filterGroup) } : {}),
    }).url
}
