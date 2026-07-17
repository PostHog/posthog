import { MakeLogicType, actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'

import { escapeHogQLString, hogql } from '~/queries/utils'
import { LogEntryLevel, PersonType } from '~/types'

import { hogFunctionsRerunCreate } from 'products/cdp/frontend/generated/api'
import type { HogInvocationRerunFilterStatusEnumApi } from 'products/cdp/frontend/generated/api.schemas'
import { hogFlowsRerunCreate } from 'products/workflows/frontend/generated/api'

export const HOG_INVOCATIONS_PAGE_SIZE = 100

/** Display-side mirror of the backend cap. Backend enforces the actual limit via the
 * `HOG_INVOCATION_RERUN_MAX_COUNT` env var (Django serializer + Node CDP config). */
export const HOG_INVOCATIONS_RERUN_MAX_COUNT = 10000

export type RunStatus = 'running' | 'succeeded' | 'failed'

export type HogInvocationsFunctionKind = 'hog_function' | 'hog_flow'

export type RunRowKind = 'hog_function' | 'hog_flow' | 'hog_function_rerun' | 'hog_flow_rerun'

export const isRerunWrapperKind = (kind: RunRowKind): boolean =>
    kind === 'hog_function_rerun' || kind === 'hog_flow_rerun'

const rerunWrapperKindFor = (kind: HogInvocationsFunctionKind): RunRowKind =>
    kind === 'hog_flow' ? 'hog_flow_rerun' : 'hog_function_rerun'

export interface HogInvocationRow {
    invocation_id: string
    function_kind: RunRowKind
    status: RunStatus
    attempts: number
    is_retry: boolean
    error_kind: string
    error_message: string
    scheduled_at: string
    first_scheduled_at: string
    started_at: string | null
    finished_at: string | null
    duration_ms: number | null
    event_uuid: string
    distinct_id: string
    person_id: string
    parent_run_id: string
    /**
     * Worst log-entry level for this invocation (`error` > `warn`), or null.
     * Surfaces async problems (e.g. an SES bounce/complaint logged after the
     * invocation already finished `succeeded`) so a run that went wrong doesn't
     * read as a clean success at the row level.
     */
    problem_log_level: 'warn' | 'error' | null
}

export type RunsOrderBy = 'latest_scheduled' | 'first_scheduled'

export interface HogInvocationsFilters {
    date_from: string
    date_to?: string
    status?: RunStatus[]
    error_kind?: string[]
    /**
     * Row-kind filter: scope the list to real invocations (`hog_function` /
     * `hog_flow`), to rerun wrapper jobs (`*_rerun`), or show both.
     */
    kind?: 'invocations' | 'rerun_jobs'
    search?: string
    order_by?: RunsOrderBy
    /**
     * Show only invocations that logged an error or warning entry (e.g. an SES bounce/complaint
     * that arrives after the run already finished `succeeded`). Status is execution-based, so these
     * aren't otherwise findable here without scanning the logs tab.
     */
    problem_only?: boolean
    /**
     * UUID of a person picked from the person search chip. Resolved on the frontend via
     * `api.persons.list` (Django), then applied to the invocations query as a hard
     * `AND person_id = '<uuid>'`. Keeps the invocations query on its own CH cluster —
     * no cross-shard subquery against `persons`.
     */
    person_uuid?: string
    log_levels?: LogEntryLevel[]
}

export interface HogInvocationsLogicProps {
    /** HogFunction.id or HogFlow.id */
    id: string
    functionKind: HogInvocationsFunctionKind
    /**
     * Scope the list to invocations spawned by a single parent run. Batch-triggered
     * workflows fan out one child invocation per person, each tagged with the batch
     * job's id as `parent_run_id` — passing it here renders that broadcast's runs on
     * their own, so the batch scene can group runs by job (see `WorkflowBatchInvocations`).
     */
    parentRunId?: string
    /**
     * Override the default date window (`-24h`). The per-job batch view anchors this to
     * the job's creation time so a broadcast's runs are in range no matter how old it is.
     */
    defaultDateFrom?: string
}

export interface SparklineSeries {
    name: RunStatus
    color: string
    values: number[]
}

export interface SparklineData {
    /** ISO timestamps for each bucket. */
    dates: string[]
    series: SparklineSeries[]
}

export interface BulkRerunParams {
    date_from: string
    date_to?: string
    status?: RunStatus[]
    error_kind?: string[]
    max_count?: number
    max_attempts?: number
}

const URL_PARAM_PREFIX = 'inv_'
const URL_PARAMS = {
    date_from: `${URL_PARAM_PREFIX}date_from`,
    date_to: `${URL_PARAM_PREFIX}date_to`,
    status: `${URL_PARAM_PREFIX}status`,
    error_kind: `${URL_PARAM_PREFIX}error_kind`,
    kind: `${URL_PARAM_PREFIX}kind`,
    search: `${URL_PARAM_PREFIX}search`,
    order_by: `${URL_PARAM_PREFIX}order`,
    problem_only: `${URL_PARAM_PREFIX}problems`,
    person_uuid: `${URL_PARAM_PREFIX}person`,
    log_levels: `${URL_PARAM_PREFIX}log_levels`,
} as const

const filtersToSearchParams = (filters: HogInvocationsFilters): Record<string, string | undefined> => ({
    [URL_PARAMS.date_from]: filters.date_from === '-24h' ? undefined : filters.date_from,
    [URL_PARAMS.date_to]: filters.date_to,
    [URL_PARAMS.status]: filters.status?.length ? filters.status.join(',') : undefined,
    [URL_PARAMS.error_kind]: filters.error_kind?.length ? filters.error_kind.join(',') : undefined,
    [URL_PARAMS.kind]: filters.kind,
    [URL_PARAMS.search]: filters.search,
    [URL_PARAMS.order_by]: filters.order_by === 'first_scheduled' ? undefined : filters.order_by,
    [URL_PARAMS.problem_only]: filters.problem_only ? '1' : undefined,
    [URL_PARAMS.person_uuid]: filters.person_uuid,
    [URL_PARAMS.log_levels]: filters.log_levels?.length ? filters.log_levels.join(',') : undefined,
})

const searchParamsToFilters = (searchParams: Record<string, string | undefined>): Partial<HogInvocationsFilters> => {
    const next: Partial<HogInvocationsFilters> = {}
    const dateFrom = searchParams[URL_PARAMS.date_from]
    if (dateFrom) {
        next.date_from = dateFrom
    }
    if (searchParams[URL_PARAMS.date_to]) {
        next.date_to = searchParams[URL_PARAMS.date_to]
    }
    const status = searchParams[URL_PARAMS.status]
    if (status) {
        next.status = status.split(',').filter((s): s is RunStatus => ['running', 'succeeded', 'failed'].includes(s))
    }
    const errorKind = searchParams[URL_PARAMS.error_kind]
    if (errorKind) {
        next.error_kind = errorKind.split(',').filter(Boolean)
    }
    const kind = searchParams[URL_PARAMS.kind]
    if (kind === 'invocations' || kind === 'rerun_jobs') {
        next.kind = kind
    }
    if (searchParams[URL_PARAMS.search]) {
        next.search = searchParams[URL_PARAMS.search]
    }
    const orderBy = searchParams[URL_PARAMS.order_by]
    if (orderBy === 'first_scheduled' || orderBy === 'latest_scheduled') {
        next.order_by = orderBy
    }
    if (searchParams[URL_PARAMS.problem_only]) {
        next.problem_only = true
    }
    if (searchParams[URL_PARAMS.person_uuid]) {
        next.person_uuid = searchParams[URL_PARAMS.person_uuid]
    }
    const logLevels = searchParams[URL_PARAMS.log_levels]
    if (logLevels) {
        next.log_levels = logLevels.split(',').filter(Boolean) as LogEntryLevel[]
    }
    return next
}

const DEFAULT_FILTERS: HogInvocationsFilters = {
    date_from: '-24h',
    date_to: undefined,
    status: undefined,
    error_kind: undefined,
    kind: undefined,
    search: undefined,
    order_by: 'first_scheduled',
    person_uuid: undefined,
}

/**
 * Build the `inv_`-prefixed router search params that deep-link the Invocations tab to a filter
 * subset. Lets callers outside the tab (e.g. the workflow metrics tiles) point at it without
 * duplicating the URL param scheme. Unset keys fall back to defaults and are dropped from the URL.
 */
export function buildHogInvocationsSearchParams(filters: Partial<HogInvocationsFilters>): Record<string, string> {
    const params = filtersToSearchParams({ ...DEFAULT_FILTERS, ...filters })
    return Object.fromEntries(
        Object.entries(params).filter((entry): entry is [string, string] => entry[1] !== undefined)
    )
}

const AUTO_REFRESH_INTERVAL_MS = 10000
// After a rerun is enqueued the matching rows aren't `running` yet (the worker
// drains asynchronously), so the `hasRunningRows` guard alone wouldn't restart
// polling. Force a short polling window so the re-run rows surface on their own.
const FORCE_REFRESH_WINDOW_MS = 30000

const scheduleAutoRefresh = (
    // Kea types `cache` as `Record<string, any>` upstream — that's where the
    // `disposables` plugin attaches its handle, but the registration is
    // dynamic so the narrow type isn't visible at this call site.
    cache: Record<string, any>,
    actions: { loadRuns: (payload: null) => void },
    values: { hasRunningRows: boolean; runsLoading: boolean }
): void => {
    const forcing = typeof cache.forceRefreshUntil === 'number' && Date.now() < cache.forceRefreshUntil
    if (!values.hasRunningRows && !forcing) {
        return
    }
    cache.disposables.add(() => {
        const timeoutId = setTimeout(() => {
            // Skip this tick if a load is still in flight — don't stack a second
            // heavy aggregation on ClickHouse. Re-arm so polling resumes once it settles.
            if (values.runsLoading) {
                scheduleAutoRefresh(cache, actions, values)
            } else {
                actions.loadRuns(null)
            }
        }, AUTO_REFRESH_INTERVAL_MS)
        return () => clearTimeout(timeoutId)
    }, 'autoRefresh')
}

/**
 * Convert a relative date-picker string (`-1h`, `-7d`, `-3w`) to its duration
 * in hours. Can't reuse `dateStringToDayJs` for this — that one anchors
 * relative strings against `startOf('day')`, so `-1h` resolves to "yesterday
 * 23:00", not "1 hour ago". Returns `null` for absolute / unknown shapes.
 */
const RELATIVE_DATE_REGEX = /^-(\d+)([sMhdwmqy])$/
const parseRelativeHours = (value: string | undefined): number | null => {
    if (!value) {
        return null
    }
    const match = RELATIVE_DATE_REGEX.exec(value)
    if (!match) {
        return null
    }
    const n = parseInt(match[1], 10)
    // PostHog convention: uppercase `M` = minutes (lowercase `m` = month). See
    // `frontend/src/lib/utils.tsx` for the master mapping.
    const hoursPerUnit: Record<string, number> = {
        s: 1 / 3600,
        M: 1 / 60,
        h: 1,
        d: 24,
        w: 24 * 7,
        m: 24 * 30,
        q: 24 * 90,
        y: 24 * 365,
    }
    return n * (hoursPerUnit[match[2]] ?? 0)
}

/**
 * Resolve the filter's date range to concrete dayjs endpoints. Centralizing
 * this so the sparkline's bucket sizing AND its boundary generation see the
 * same window (otherwise the chart's x-axis can drift away from the actual
 * filter the table is using).
 */
export const resolveDateRange = (filters: {
    date_from?: string
    date_to?: string
}): { start: dayjs.Dayjs; end: dayjs.Dayjs } => {
    const end = filters.date_to ? (dateStringToDayJs(filters.date_to) ?? dayjs()) : dayjs()
    const relHours = parseRelativeHours(filters.date_from)
    if (relHours !== null) {
        return { start: end.subtract(relHours, 'hour'), end }
    }
    const start = dateStringToDayJs(filters.date_from ?? null) ?? end.subtract(24, 'hour')
    return { start, end }
}

/**
 * Inline date predicate for the inner subquery's WHERE clause. `filtersOverride`
 * doesn't bind to a timestamp field on `hog_invocation_results` (no marker on
 * the schema), so we apply the window directly. UTC + the CH DateTime64 literal
 * format keeps partition pruning working.
 */
export const dateClauseFor = (filters: HogInvocationsFilters): ReturnType<typeof hogql.raw> => {
    const { start, end } = resolveDateRange(filters)
    // HogQL interprets bare datetime literals in the *team* timezone (DateTime
    // fields are compared as toTimeZone(field, team_tz)), so format the window
    // bounds in the team tz — NOT UTC — or the filter is shifted by the team's
    // offset for any non-UTC project. Mirrors `toAbsoluteClickhouseTimestamp`.
    const teamTimezone = teamLogic.findMounted()?.values.currentTeam?.timezone ?? 'UTC'
    const fmt = (d: dayjs.Dayjs): string => d.tz(teamTimezone).format('YYYY-MM-DD HH:mm:ss.SSS')
    return hogql.raw(`AND scheduled_at >= '${fmt(start)}' AND scheduled_at < '${fmt(end)}'`)
}

/**
 * `function_kind` predicate driven by the kind filter — `invocations` returns
 * only real rows, `rerun_jobs` returns only the wrapper rows, and the default
 * (undefined) returns both kinds for this function id.
 */
export const kindClauseFor = (
    props: HogInvocationsLogicProps,
    filters: HogInvocationsFilters
): ReturnType<typeof hogql.raw> => {
    const wrapperKind = rerunWrapperKindFor(props.functionKind)
    if (filters.kind === 'invocations') {
        return hogql.raw(`function_kind = '${props.functionKind}'`)
    }
    if (filters.kind === 'rerun_jobs') {
        return hogql.raw(`function_kind = '${wrapperKind}'`)
    }
    return hogql.raw(`function_kind IN ('${props.functionKind}', '${wrapperKind}')`)
}

/**
 * Optional predicate scoping the list to one parent run (a batch job). Empty when
 * `parentRunId` isn't set, so the flat list is unchanged. Placement depends on the query:
 * put it in WHERE when it reads the physical `parent_run_id` column, but in HAVING when the
 * SELECT aliases `parent_run_id` to `argMax(parent_run_id, version)` — there the name
 * resolves to that aggregate alias, which ClickHouse rejects in WHERE.
 */
export const parentClauseFor = (props: HogInvocationsLogicProps): ReturnType<typeof hogql.raw> =>
    props.parentRunId ? hogql.raw(`AND parent_run_id = ${escapeHogQLString(props.parentRunId)}`) : hogql.raw('')

/**
 * Optional predicate restricting to invocations that logged an error/warning entry. Uses a
 * `log_entries` subquery (resolved server-side, so no client-side id list) keyed by the same
 * source the per-row logs use. Deliberately not date-scoped: a bounce/complaint can land after
 * the run's scheduled window, and the outer `scheduled_at` filter already constrains which
 * invocations appear. Returns an empty clause when the filter is off.
 */
export const problemClauseFor = (
    props: HogInvocationsLogicProps,
    filters: HogInvocationsFilters
): ReturnType<typeof hogql.raw> => {
    if (!filters.problem_only) {
        return hogql.raw('')
    }
    return hogql.raw(
        `AND invocation_id IN (` +
            `SELECT instance_id FROM log_entries ` +
            `WHERE log_source = ${escapeHogQLString(props.functionKind)} ` +
            `AND log_source_id = ${escapeHogQLString(props.id)} ` +
            `AND lower(level) IN ('error', 'warn'))`
    )
}

/**
 * The main search box: one term matches an exact invocation / event / distinct / person id, OR — like
 * the old Logs tab — a run that logged an entry whose message contains it (case-insensitive
 * substring). `log_levels` narrows only the message match and is set solely by metric drill-downs
 * (e.g. the "Bounced" tile carries WARN/ERROR so it doesn't also match the INFO "Email sent to
 * bounce@…" log); manual searches leave it unset and match any level. The message subquery is
 * deliberately not date-scoped — a bounce/complaint can land after the run's scheduled window, and
 * the outer `scheduled_at` filter already bounds which invocations appear. Empty when no search.
 */
export const buildSearchClause = (
    props: HogInvocationsLogicProps,
    filters: HogInvocationsFilters
): ReturnType<typeof hogql.raw> => {
    const search = filters.search?.trim()
    if (!search) {
        return hogql.raw('')
    }
    const levels = filters.log_levels ?? []
    const levelClause = levels.length
        ? `AND lower(level) IN (${levels.map((level) => escapeHogQLString(level.toLowerCase())).join(',')})`
        : ''
    // Escape ILIKE wildcards for the message arm so a term with % or _ (e.g. "50%") matches literally
    // (ClickHouse ILIKE uses backslash as its escape char); the exact-id arms use the raw term.
    const likeTerm = search.replace(/[\\%_]/g, '\\$&')
    return hogql.raw(
        `AND (` +
            `invocation_id = ${escapeHogQLString(search)} ` +
            `OR event_uuid = ${escapeHogQLString(search)} ` +
            `OR distinct_id = ${escapeHogQLString(search)} ` +
            `OR person_id = ${escapeHogQLString(search)} ` +
            `OR invocation_id IN (` +
            `SELECT instance_id FROM log_entries ` +
            `WHERE log_source = ${escapeHogQLString(props.functionKind)} ` +
            `AND log_source_id = ${escapeHogQLString(props.id)} ` +
            `AND message ILIKE concat('%', ${escapeHogQLString(likeTerm)}, '%') ` +
            `${levelClause}))`
    )
}

/**
 * Tier selection for the sparkline. Each tier carries both the HogQL bucket
 * expression and the equivalent client-side interval (in ms) so we can
 * generate every bucket boundary in the filter range, not just the ones CH
 * returned data for. Tiers (by total range): <24h minutely, ≤4d 15-min,
 * ≤7d hourly, otherwise daily.
 */
interface SparklineTier {
    intervalMs: number
    bucketExpr: string
}
const pickSparklineTier = (filters: HogInvocationsFilters): SparklineTier => {
    const { start, end } = resolveDateRange(filters)
    const hours = end.diff(start, 'hour')
    if (hours < 24) {
        return { intervalMs: 60_000, bucketExpr: 'toStartOfMinute(first_scheduled)' }
    }
    if (hours <= 4 * 24) {
        return {
            intervalMs: 15 * 60_000,
            bucketExpr: 'toStartOfInterval(first_scheduled, INTERVAL 15 MINUTE)',
        }
    }
    if (hours <= 7 * 24) {
        return { intervalMs: 60 * 60_000, bucketExpr: 'toStartOfHour(first_scheduled)' }
    }
    return { intervalMs: 24 * 60 * 60_000, bucketExpr: 'toStartOfDay(first_scheduled)' }
}

/**
 * Walk the filter range and emit every bucket boundary as an ISO string.
 * Snaps to interval-aligned ms (matching CH's epoch-aligned
 * `toStartOfInterval` / `toStartOfMinute` etc.), so the keys we use to look
 * up CH counts line up regardless of timezone formatting.
 */
const generateSparklineBuckets = (filters: HogInvocationsFilters, intervalMs: number): string[] => {
    const { start, end } = resolveDateRange(filters)
    const snap = (t: dayjs.Dayjs): number => Math.floor(t.valueOf() / intervalMs) * intervalMs
    const out: string[] = []
    for (let ms = snap(start); ms < end.valueOf(); ms += intervalMs) {
        out.push(dayjs(ms).toISOString())
    }
    return out
}

const SPARKLINE_STATUS_COLORS: Record<RunStatus, string> = {
    running: 'warning',
    succeeded: 'success',
    failed: 'danger',
}

async function fetchSparkline(props: HogInvocationsLogicProps, filters: HogInvocationsFilters): Promise<SparklineData> {
    const { intervalMs, bucketExpr } = pickSparklineTier(filters)

    // Filters reference the SELECT aliases (status / error_kind) so we don't
    // re-wrap in argMax inline — that would collide with the alias and
    // produce a nested aggregate error.
    // `escapeHogQLString` handles all special chars (quotes, backslashes, null
    // bytes) using the same path as the `hogql` template tag — a `.replace(/'/g, …)`
    // pass on its own is bypassable (e.g. `\' OR 1=1 --`).
    const optionalStatusClause = filters.status?.length
        ? hogql.raw(`AND status IN (${filters.status.map(escapeHogQLString).join(',')})`)
        : hogql.raw('')
    const optionalErrorKindClause = filters.error_kind?.length
        ? hogql.raw(`AND error_kind IN (${filters.error_kind.map(escapeHogQLString).join(',')})`)
        : hogql.raw('')
    // Person filter is applied as a hard equality on `person_id`. The UUID is resolved
    // client-side via `api.persons.list` (Django/Postgres) — we can't join `persons` in
    // the invocations query itself because the two tables live on different CH clusters.
    const optionalPersonClause = filters.person_uuid
        ? hogql.raw(`AND person_id = ${escapeHogQLString(filters.person_uuid)}`)
        : hogql.raw('')

    const kindClause = kindClauseFor(props, filters)
    const dateClause = dateClauseFor(filters)
    const query = hogql`
        SELECT
            ${hogql.raw(bucketExpr)} AS bucket,
            status,
            count() AS n
        FROM (
            SELECT
                invocation_id,
                argMax(status, version)         AS status,
                argMax(error_kind, version)     AS error_kind,
                argMax(event_uuid, version)     AS event_uuid,
                argMax(distinct_id, version)    AS distinct_id,
                argMax(person_id, version)      AS person_id,
                argMax(first_scheduled_at, version) AS first_scheduled
            FROM posthog.hog_invocation_results
            WHERE ${kindClause}
              AND function_id = ${props.id}
              ${parentClauseFor(props)}
              ${dateClause}
            GROUP BY invocation_id, function_kind
            HAVING argMax(is_deleted, version) = 0
               ${optionalStatusClause}
               ${optionalErrorKindClause}
               ${buildSearchClause(props, filters)}
               ${optionalPersonClause}
               ${problemClauseFor(props, filters)}
        )
        GROUP BY bucket, status
        ORDER BY bucket
    `
    const response = await api.queryHogQL(
        query,
        { scene: 'HogInvocations', productKey: 'pipeline_destinations' },
        {
            refresh: 'force_blocking',
            filtersOverride: { date_from: filters.date_from, date_to: filters.date_to },
        }
    )

    // Pivot CH results keyed on bucket-as-ms so the lookup is tolerant of
    // string-format differences between CH's serialization and dayjs's
    // ISO output.
    const cellsByMs: Record<number, Record<RunStatus, number>> = {}
    for (const row of response.results ?? []) {
        const [bucket, status, n] = row as unknown as [string, RunStatus, number]
        if (!bucket) {
            continue
        }
        const ms = dayjs(bucket).valueOf()
        cellsByMs[ms] = cellsByMs[ms] ?? { running: 0, succeeded: 0, failed: 0 }
        cellsByMs[ms][status] = Number(n ?? 0)
    }
    // Walk every bucket in the filter range — not just the ones CH returned
    // data for — so the chart's x-axis spans the user's selected window even
    // when activity is concentrated in a tiny slice of it.
    const dates = generateSparklineBuckets(filters, intervalMs)
    const buildValues = (status: RunStatus): number[] => dates.map((d) => cellsByMs[dayjs(d).valueOf()]?.[status] ?? 0)
    const series: SparklineSeries[] = (['failed', 'running', 'succeeded'] as RunStatus[]).map((status) => ({
        name: status,
        color: SPARKLINE_STATUS_COLORS[status],
        values: buildValues(status),
    }))
    return { dates, series }
}

async function fetchRunsPage(
    props: HogInvocationsLogicProps,
    filters: HogInvocationsFilters,
    offset: number
): Promise<HogInvocationRow[]> {
    // HAVING clauses reference the SELECT aliases below — wrapping the column
    // again as `argMax(status, version)` makes HogQL substitute `status` for
    // its alias and produce a nested aggregate.
    const optionalStatusClause = filters.status?.length
        ? hogql.raw(`AND status IN (${filters.status.map(escapeHogQLString).join(', ')})`)
        : hogql.raw('')
    const optionalErrorKindClause = filters.error_kind?.length
        ? hogql.raw(`AND error_kind IN (${filters.error_kind.map(escapeHogQLString).join(', ')})`)
        : hogql.raw('')
    // Person filter is applied as a hard equality on `person_id`. The UUID is resolved
    // client-side via `api.persons.list` (Django/Postgres) — we can't join `persons` in
    // the invocations query itself because the two tables live on different CH clusters.
    const optionalPersonClause = filters.person_uuid
        ? hogql.raw(`AND person_id = ${escapeHogQLString(filters.person_uuid)}`)
        : hogql.raw('')

    // `ORDER BY max(scheduled_at)` is safe only because the SELECT alias isn't
    // named `scheduled_at` — otherwise HogQL substitutes the alias and produces
    // `max(max(scheduled_at))`.
    const orderClause =
        filters.order_by === 'first_scheduled'
            ? hogql.raw('ORDER BY argMax(first_scheduled_at, version) DESC, invocation_id DESC')
            : hogql.raw('ORDER BY max(scheduled_at) DESC, invocation_id DESC')
    const kindClause = kindClauseFor(props, filters)
    const dateClause = dateClauseFor(filters)
    const query = hogql`
        SELECT
            invocation_id,
            function_kind                   AS function_kind,
            argMax(status, version)         AS status,
            argMax(attempts, version)       AS attempts,
            argMax(is_retry, version)       AS is_retry,
            argMax(error_kind, version)     AS error_kind,
            argMax(error_message, version)  AS error_message,
            max(scheduled_at)               AS latest_scheduled_at,
            argMax(first_scheduled_at, version) AS first_scheduled,
            argMax(started_at, version)     AS started_at,
            argMax(finished_at, version)    AS finished_at,
            argMax(duration_ms, version)    AS duration_ms,
            argMax(event_uuid, version)     AS event_uuid,
            argMax(distinct_id, version)    AS distinct_id,
            argMax(person_id, version)      AS person_id,
            argMax(parent_run_id, version)  AS parent_run_id
        FROM posthog.hog_invocation_results
        WHERE ${kindClause}
          AND function_id = ${props.id}
          ${dateClause}
        GROUP BY invocation_id, function_kind
        HAVING argMax(is_deleted, version) = 0
           ${parentClauseFor(props)}
           ${optionalStatusClause}
           ${optionalErrorKindClause}
           ${buildSearchClause(props, filters)}
           ${optionalPersonClause}
           ${problemClauseFor(props, filters)}
        ${orderClause}
        LIMIT ${HOG_INVOCATIONS_PAGE_SIZE}
        OFFSET ${offset}
    `

    const response = await api.queryHogQL(
        query,
        { scene: 'HogInvocations', productKey: 'pipeline_destinations' },
        {
            refresh: 'force_blocking',
            filtersOverride: {
                date_from: filters.date_from,
                date_to: filters.date_to,
            },
        }
    )

    const rows = (response.results ?? []).map((row): HogInvocationRow => {
        const [
            invocation_id,
            function_kind,
            status,
            attempts,
            is_retry,
            error_kind,
            error_message,
            scheduled_at,
            first_scheduled_at,
            started_at,
            finished_at,
            duration_ms,
            event_uuid,
            distinct_id,
            person_id,
            parent_run_id,
        ] = row as unknown as [
            string,
            RunRowKind,
            RunStatus,
            number,
            number,
            string,
            string,
            string,
            string,
            string | null,
            string | null,
            number | null,
            string,
            string,
            string,
            string,
        ]
        return {
            invocation_id,
            function_kind,
            status,
            attempts,
            is_retry: Boolean(is_retry),
            error_kind,
            error_message,
            scheduled_at,
            first_scheduled_at,
            started_at,
            finished_at,
            duration_ms,
            event_uuid,
            distinct_id,
            person_id,
            parent_run_id,
            problem_log_level: null,
        }
    })

    // Problem-level enrichment is deferred to `enrichProblems` so the table renders
    // on the main query alone — the severity lookup patches the rows in afterwards.
    return rows
}

/**
 * Worst log-entry level (`warn`/`error`) per invocation for the given page ids.
 * An SES bounce/complaint (and similar async failures) writes an error/warn log entry
 * after the invocation already finished `succeeded`, so without this a delivery failure
 * reads as a clean success. Kept off the runs query's critical path — see `enrichProblems`.
 */
async function fetchProblemLevels(
    props: HogInvocationsLogicProps,
    ids: string[]
): Promise<Record<string, 'warn' | 'error'>> {
    if (ids.length === 0) {
        return {}
    }
    const idClause = hogql.raw(`instance_id IN (${ids.map(escapeHogQLString).join(',')})`)
    const severityQuery = hogql`
        SELECT instance_id, max(multiIf(lower(level) = 'error', 2, lower(level) = 'warn', 1, 0)) AS sev
        FROM log_entries
        WHERE log_source = ${props.functionKind}
          AND log_source_id = ${props.id}
          AND ${idClause}
        GROUP BY instance_id
        HAVING sev > 0
    `
    const severityResponse = await api.queryHogQL(severityQuery, {
        scene: 'HogInvocations',
        productKey: 'pipeline_destinations',
    })
    const levelByInvocationId: Record<string, 'warn' | 'error'> = {}
    for (const severityRow of severityResponse.results ?? []) {
        const [instanceId, sev] = severityRow as unknown as [string, number]
        levelByInvocationId[instanceId] = Number(sev) >= 2 ? 'error' : 'warn'
    }
    return levelByInvocationId
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface hogInvocationsLogicValues {
    canBulkRerun: boolean
    expandedIds: Record<string, boolean>
    filters: HogInvocationsFilters
    hasLoadedOnce: boolean
    hasMore: boolean
    hasRunningRows: boolean
    personPropertiesById: Record<
        string,
        {
            distinct_ids?: string[]
            properties: Record<string, any>
        }
    >
    personPropertiesByIdLoading: boolean
    personSearchResults: PersonType[]
    personSearchResultsLoading: boolean
    pickedPerson: PersonType | null
    rerunableSelectedIds: string[]
    runs: HogInvocationRow[]
    runsLoading: boolean
    selectAllState: 'all' | 'none' | 'some'
    selectableIds: string[]
    selectedCount: number
    selectedIds: Record<string, boolean>
    sparkline: SparklineData | null
    sparklineLoading: boolean
    statusCounts: Record<RunStatus, number>
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface hogInvocationsLogicActions {
    bulkRerun: (params: BulkRerunParams) => {
        params: BulkRerunParams
    }
    clearSelected: () => {
        value: true
    }
    enrichProblems: (invocationIds: string[] | null) => string[] | null
    enrichProblemsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    enrichProblemsSuccess: (
        runs: HogInvocationRow[],
        payload?: string[] | null
    ) => {
        runs: HogInvocationRow[]
        payload?: string[] | null
    }
    hydratePeople: (personIds: string[]) => {
        personIds: string[]
    }
    hydratePeopleFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    hydratePeopleSuccess: (
        personPropertiesById: Record<
            string,
            {
                distinct_ids?: string[] | undefined
                properties: Record<string, any>
            }
        >,
        payload?: {
            personIds: string[]
        }
    ) => {
        personPropertiesById: Record<
            string,
            {
                distinct_ids?: string[] | undefined
                properties: Record<string, any>
            }
        >
        payload?: {
            personIds: string[]
        }
    }
    loadMore: (_: any) => any
    loadMoreFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadMoreSuccess: (
        runs: HogInvocationRow[],
        payload?: any
    ) => {
        runs: HogInvocationRow[]
        payload?: any
    }
    loadRuns: (_: any) => any
    loadRunsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadRunsSuccess: (
        runs: HogInvocationRow[],
        payload?: any
    ) => {
        runs: HogInvocationRow[]
        payload?: any
    }
    loadSparkline: (_: any) => any
    loadSparklineFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSparklineSuccess: (
        sparkline: SparklineData,
        payload?: any
    ) => {
        sparkline: SparklineData
        payload?: any
    }
    refresh: () => {
        value: true
    }
    rerunInvocations: (invocationIds: string[]) => {
        invocationIds: string[]
    }
    resetFilters: () => {
        value: true
    }
    searchPersons: ({ search }: { search: string }) => {
        search: string
    }
    searchPersonsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    searchPersonsSuccess: (
        personSearchResults: PersonType[],
        payload?: {
            search: string
        }
    ) => {
        personSearchResults: PersonType[]
        payload?: {
            search: string
        }
    }
    setExpanded: (
        invocationId: string,
        expanded: boolean
    ) => {
        expanded: boolean
        invocationId: string
    }
    setFilters: (filters: Partial<HogInvocationsFilters>) => {
        filters: Partial<HogInvocationsFilters>
    }
    setHasMore: (hasMore: boolean) => {
        hasMore: boolean
    }
    setPickedPerson: (person: PersonType | null) => {
        person: PersonType | null
    }
    setSelectedIds: (ids: string[]) => {
        ids: string[]
    }
    toggleSelected: (invocationId: string) => {
        invocationId: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface hogInvocationsLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        statusCounts: (runs: HogInvocationRow[]) => Record<RunStatus, number>
        selectedCount: (selectedIds: Record<string, boolean>) => number
        canBulkRerun: (selectedCount: number) => boolean
        rerunableSelectedIds: (selectedIds: Record<string, boolean>, runs: HogInvocationRow[]) => string[]
        hasRunningRows: (runs: HogInvocationRow[]) => boolean
        selectableIds: (runs: HogInvocationRow[]) => string[]
        selectAllState: (selectedIds: Record<string, boolean>, selectableIds: string[]) => 'all' | 'none' | 'some'
    }
}

export type hogInvocationsLogicType = MakeLogicType<
    hogInvocationsLogicValues,
    hogInvocationsLogicActions,
    HogInvocationsLogicProps,
    hogInvocationsLogicMeta
>

/**
 * Rerun is async — the `/rerun` endpoint enqueues a cyclotron wrapper job;
 * new lifecycle rows show up here once the worker drains it.
 */
export const hogInvocationsLogic = kea<hogInvocationsLogicType>([
    path((id) => ['scenes', 'hog-functions', 'invocations', 'hogInvocationsLogic', id]),
    props({} as HogInvocationsLogicProps),
    key((props) => `${props.functionKind}:${props.id}${props.parentRunId ? `:${props.parentRunId}` : ''}`),

    actions({
        setFilters: (filters: Partial<HogInvocationsFilters>) => ({ filters }),
        resetFilters: true,
        refresh: true,
        toggleSelected: (invocationId: string) => ({ invocationId }),
        clearSelected: true,
        setSelectedIds: (ids: string[]) => ({ ids }),
        hydratePeople: (personIds: string[]) => ({ personIds }),
        setExpanded: (invocationId: string, expanded: boolean) => ({ invocationId, expanded }),
        rerunInvocations: (invocationIds: string[]) => ({ invocationIds }),
        bulkRerun: (params: BulkRerunParams) => ({ params }),
        setHasMore: (hasMore: boolean) => ({ hasMore }),
        // Person filter picker: user picks a person from the typeahead → chip stays in the
        // input row. Passing `null` clears the filter. `setFilters` still owns URL sync and
        // refresh; `pickedPerson` just carries display state so the chip can render name/email
        // without an extra roundtrip.
        setPickedPerson: (person: PersonType | null) => ({ person }),
    }),

    reducers(({ props }) => {
        const defaultFilters: HogInvocationsFilters = props.defaultDateFrom
            ? { ...DEFAULT_FILTERS, date_from: props.defaultDateFrom }
            : DEFAULT_FILTERS
        return {
            filters: [
                defaultFilters,
                {
                    setFilters: (state, { filters }) => ({ ...state, ...filters }),
                    resetFilters: () => defaultFilters,
                },
            ],
            selectedIds: [
                {} as Record<string, boolean>,
                {
                    toggleSelected: (state, { invocationId }) => {
                        const next = { ...state }
                        if (next[invocationId]) {
                            delete next[invocationId]
                        } else {
                            next[invocationId] = true
                        }
                        return next
                    },
                    clearSelected: () => ({}),
                    setSelectedIds: (_, { ids }) => Object.fromEntries(ids.map((id) => [id, true])),
                },
            ],
            expandedIds: [
                {} as Record<string, boolean>,
                {
                    setExpanded: (state, { invocationId, expanded }) => {
                        const next = { ...state }
                        if (expanded) {
                            next[invocationId] = true
                        } else {
                            delete next[invocationId]
                        }
                        return next
                    },
                },
            ],
            hasMore: [
                false,
                {
                    setHasMore: (_, { hasMore }) => hasMore,
                    setFilters: () => false,
                    resetFilters: () => false,
                },
            ],
            hasLoadedOnce: [
                false,
                {
                    setHasMore: () => true,
                },
            ],
            pickedPerson: [
                null as PersonType | null,
                {
                    setPickedPerson: (_, { person }) => person,
                    // A URL-driven filter change without a matching pickedPerson means we came in
                    // from a shared link — clear the stale display until the hydrator populates it.
                    // `person.uuid` is the actual UUID; `person.id` is Django's numeric PK.
                    setFilters: (state, { filters }) =>
                        'person_uuid' in filters && filters.person_uuid !== state?.uuid ? null : state,
                    resetFilters: () => null,
                },
            ],
        }
    }),

    loaders(({ props, values, actions, cache }) => ({
        runs: [
            [] as HogInvocationRow[],
            {
                loadRuns: async (_, breakpoint) => {
                    await breakpoint(100)
                    const rows = await fetchRunsPage(props, values.filters, 0)
                    breakpoint()
                    // Carry forward already-resolved problem levels so the indicator
                    // doesn't flicker off each refresh before `enrichProblems` re-resolves it.
                    const priorLevels = new Map(values.runs.map((r) => [r.invocation_id, r.problem_log_level]))
                    for (const row of rows) {
                        row.problem_log_level = priorLevels.get(row.invocation_id) ?? null
                    }
                    actions.setHasMore(rows.length >= HOG_INVOCATIONS_PAGE_SIZE)
                    return rows
                },
                loadMore: async (_, breakpoint) => {
                    await breakpoint(50)
                    const offset = values.runs.length
                    const newRows = await fetchRunsPage(props, values.filters, offset)
                    breakpoint()
                    actions.setHasMore(newRows.length >= HOG_INVOCATIONS_PAGE_SIZE)
                    // Prior pages are already enriched — stash the new ids so
                    // `loadMoreSuccess` scopes the severity query to this page only.
                    cache.lastPageInvocationIds = newRows.map((r) => r.invocation_id)
                    return [...values.runs, ...newRows]
                },
                // Deferred, best-effort enrichment — runs after the table renders and
                // patches the worst log level onto each row without blocking the load.
                // `invocationIds` scopes the severity query (Load More passes just the
                // new page); null enriches every loaded row (refresh path).
                enrichProblems: async (invocationIds: string[] | null, breakpoint) => {
                    const ids = invocationIds ?? values.runs.map((r) => r.invocation_id)
                    if (ids.length === 0) {
                        return values.runs
                    }
                    let levelByInvocationId: Record<string, 'warn' | 'error'>
                    try {
                        levelByInvocationId = await fetchProblemLevels(props, ids)
                    } catch {
                        // Leave levels as-is — the run statuses are still accurate.
                        return values.runs
                    }
                    breakpoint()
                    // Patch onto the *current* runs (not a pre-await snapshot) so a refresh
                    // that landed mid-flight isn't clobbered with a stale page; unresolved
                    // rows keep any carried-forward level.
                    return values.runs.map((row) => ({
                        ...row,
                        problem_log_level: levelByInvocationId[row.invocation_id] ?? row.problem_log_level ?? null,
                    }))
                },
            },
        ],
        sparkline: [
            null as SparklineData | null,
            {
                loadSparkline: async (_, breakpoint) => {
                    await breakpoint(100)
                    const data = await fetchSparkline(props, values.filters)
                    breakpoint()
                    return data
                },
            },
        ],
        personSearchResults: [
            [] as PersonType[],
            {
                searchPersons: async ({ search }: { search: string }, breakpoint) => {
                    const trimmed = search.trim()
                    if (!trimmed) {
                        return []
                    }
                    // Debounce so quick typing doesn't fan out to N requests.
                    await breakpoint(300)
                    try {
                        const response = await api.persons.list({ search: trimmed, limit: 10 })
                        breakpoint()
                        return response.results ?? []
                    } catch {
                        return []
                    }
                },
            },
        ],
        personPropertiesById: [
            {} as Record<string, { properties: Record<string, any>; distinct_ids?: string[] }>,
            {
                hydratePeople: async ({ personIds }, breakpoint) => {
                    // person_id comes from CH rows so it _should_ already be a UUID,
                    // but the values flow back through user-controlled state (URL
                    // params can seed selectedRowIds etc.). Validate as a UUID
                    // before interpolation so a malformed entry can't smuggle SQL
                    // through `toUUID('…')`.
                    const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
                    const toFetch = personIds.filter(
                        (id) => id && UUID_PATTERN.test(id) && !values.personPropertiesById[id]
                    )
                    if (toFetch.length === 0) {
                        return values.personPropertiesById
                    }
                    await breakpoint(50)
                    const idList = hogql.raw(toFetch.map((id) => `toUUID('${id}')`).join(','))
                    const query = hogql`
                        SELECT id, properties
                        FROM persons
                        WHERE id IN (${idList})
                    `
                    // Best-effort enrichment — a transient network blip just leaves the
                    // table without person props rather than surfacing an error.
                    const response = await api
                        .queryHogQL(query, {
                            scene: 'HogInvocations',
                            productKey: 'pipeline_destinations',
                        })
                        .catch(() => null)
                    if (!response) {
                        return values.personPropertiesById
                    }
                    breakpoint()
                    const next = { ...values.personPropertiesById }
                    for (const row of response.results ?? []) {
                        const [id, propsJson] = row as unknown as [string, string]
                        let properties: Record<string, any> = {}
                        try {
                            properties = JSON.parse(propsJson || '{}')
                        } catch {
                            // Malformed JSON — fall back to empty object.
                        }
                        next[id] = { properties }
                    }
                    return next
                },
            },
        ],
    })),

    selectors({
        statusCounts: [
            (s) => [s.runs],
            (runs: HogInvocationRow[]): Record<RunStatus, number> => {
                const counts: Record<RunStatus, number> = { running: 0, succeeded: 0, failed: 0 }
                for (const r of runs) {
                    counts[r.status] = (counts[r.status] ?? 0) + 1
                }
                return counts
            },
        ],
        selectedCount: [
            (s) => [s.selectedIds],
            (selectedIds: Record<string, boolean>) => Object.keys(selectedIds).length,
        ],
        canBulkRerun: [
            (s) => [s.selectedCount],
            (selectedCount: number) => selectedCount > 0 && selectedCount <= HOG_INVOCATIONS_RERUN_MAX_COUNT,
        ],
        rerunableSelectedIds: [
            (s) => [s.selectedIds, s.runs],
            (selectedIds: Record<string, boolean>, runs: HogInvocationRow[]): string[] => {
                const ids = Object.keys(selectedIds)
                if (ids.length === 0) {
                    return []
                }
                const byId = new Map(runs.map((r) => [r.invocation_id, r]))
                return ids.filter((id) => {
                    const row = byId.get(id)
                    // Allow rerun if row not loaded — the worker enforces its own checks.
                    return !row || (row.status !== 'running' && !isRerunWrapperKind(row.function_kind))
                })
            },
        ],
        hasRunningRows: [
            (s) => [s.runs],
            (runs: HogInvocationRow[]): boolean => runs.some((r) => r.status === 'running'),
        ],
        selectableIds: [
            (s) => [s.runs],
            (runs: HogInvocationRow[]): string[] =>
                runs
                    .filter((r) => !isRerunWrapperKind(r.function_kind) && r.status !== 'running')
                    .map((r) => r.invocation_id),
        ],
        selectAllState: [
            (s) => [s.selectedIds, s.selectableIds],
            (selectedIds: Record<string, boolean>, selectableIds: string[]): 'all' | 'some' | 'none' => {
                if (selectableIds.length === 0) {
                    return 'none'
                }
                const selectedCount = selectableIds.filter((id) => selectedIds[id]).length
                if (selectedCount === 0) {
                    return 'none'
                }
                return selectedCount === selectableIds.length ? 'all' : 'some'
            },
        ],
    }),

    listeners(({ props, actions, values, cache }) => ({
        refresh: () => {
            actions.loadRuns(null)
            actions.loadSparkline(null)
        },
        setFilters: async ({ filters }) => {
            actions.refresh()
            // Hydrate the picked-person display when a shared link seeds `person_uuid`
            // without a matching pickedPerson (e.g. someone pasted the URL).
            if ('person_uuid' in filters && filters.person_uuid && values.pickedPerson?.uuid !== filters.person_uuid) {
                const targetUuid = filters.person_uuid
                try {
                    const byUuid = await api.persons.getByUUIDs([targetUuid])
                    // Re-check after the await: the user may have cleared the filter or picked a
                    // different person while the hydrate was in flight. Restoring the stale hit
                    // would silently reload invocations for the wrong person.
                    if (values.filters.person_uuid !== targetUuid) {
                        return
                    }
                    const person = byUuid[targetUuid]
                    if (person) {
                        actions.setPickedPerson(person)
                    }
                } catch {
                    // Best-effort; the chip falls back to showing the raw UUID.
                }
            }
        },
        resetFilters: () => {
            actions.refresh()
        },
        setPickedPerson: ({ person }) => {
            actions.setFilters({ person_uuid: person?.uuid ?? undefined })
        },
        loadRunsSuccess: () => {
            scheduleAutoRefresh(cache, actions, values)
            // Full-list enrichment: a 10s poll can surface brand-new invocation ids.
            actions.enrichProblems(null)
            const personIds = Array.from(new Set(values.runs.map((r) => r.person_id).filter(Boolean)))
            if (personIds.length > 0) {
                actions.hydratePeople(personIds)
            }
        },
        loadMoreSuccess: () => {
            scheduleAutoRefresh(cache, actions, values)
            actions.enrichProblems((cache.lastPageInvocationIds as string[] | undefined) ?? null)
            const personIds = Array.from(new Set(values.runs.map((r) => r.person_id).filter(Boolean)))
            if (personIds.length > 0) {
                actions.hydratePeople(personIds)
            }
        },
        rerunInvocations: async ({ invocationIds }) => {
            if (invocationIds.length === 0) {
                lemonToast.warning('Nothing to rerun')
                return
            }
            if (invocationIds.length > HOG_INVOCATIONS_RERUN_MAX_COUNT) {
                lemonToast.error(`Rerun request capped at ${HOG_INVOCATIONS_RERUN_MAX_COUNT} invocations per request`)
                return
            }

            const { filters } = values
            const teamId = ApiConfig.getCurrentTeamId()
            // `resolveDateRange` handles `-24h`-style relative strings as a
            // duration anchored to "now". Using `dateStringToDayJs` directly
            // anchors relative strings to start-of-day, which would silently
            // widen the rerun window beyond what the user sees in the table.
            const { start: rerunStart, end: rerunEnd } = resolveDateRange(filters)
            const windowStart = rerunStart.toISOString()
            const windowEnd = rerunEnd.toISOString()

            const requestBody = {
                filter: {
                    window_start: windowStart,
                    window_end: windowEnd,
                    invocation_ids: invocationIds,
                    // When rerunning specific IDs, don't restrict by status — the worker
                    // defaults a missing status to ['failed'], which would silently drop
                    // succeeded rows the user explicitly selected. The ID restriction
                    // alone determines what gets rerun (the worker still skips in-flight).
                    status: ['running', 'succeeded', 'failed'] as HogInvocationRerunFilterStatusEnumApi[],
                },
            }

            try {
                const response =
                    props.functionKind === 'hog_function'
                        ? await hogFunctionsRerunCreate(String(teamId), props.id, requestBody)
                        : await hogFlowsRerunCreate(String(teamId), props.id, requestBody)
                lemonToast.success(
                    `Rerun job ${response.rerun_job_id.slice(0, 8)}… queued. Updated rows will appear here as the worker drains the job.`
                )
                actions.clearSelected()
                // Re-run rows aren't `running` yet — force a short polling window so they surface.
                cache.forceRefreshUntil = Date.now() + FORCE_REFRESH_WINDOW_MS
                actions.loadRuns(null)
            } catch (e: any) {
                lemonToast.error(`Failed to enqueue rerun: ${e?.detail ?? e?.message ?? String(e)}`)
            }
        },
        bulkRerun: async ({ params }) => {
            const teamId = ApiConfig.getCurrentTeamId()
            // Resolve via `resolveDateRange` so `-24h` produces "24 hours ago",
            // matching the table/sparkline. Anchoring relative strings to
            // start-of-day here would silently rerun rows outside the visible
            // window.
            const { start: bulkStart, end: bulkEnd } = resolveDateRange(params)
            const windowStart = bulkStart.toISOString()
            const windowEnd = bulkEnd.toISOString()

            const requestBody = {
                filter: {
                    window_start: windowStart,
                    window_end: windowEnd,
                    status: params.status?.length
                        ? (params.status as HogInvocationRerunFilterStatusEnumApi[])
                        : undefined,
                    error_kind: params.error_kind?.length ? params.error_kind : undefined,
                    max_count: params.max_count,
                    max_attempts: params.max_attempts,
                },
            }

            try {
                const response =
                    props.functionKind === 'hog_function'
                        ? await hogFunctionsRerunCreate(String(teamId), props.id, requestBody)
                        : await hogFlowsRerunCreate(String(teamId), props.id, requestBody)
                lemonToast.success(
                    `Re-run job ${response.rerun_job_id.slice(0, 8)}… queued. Matching invocations will be re-run in the background.`
                )
                // Re-run rows aren't `running` yet — force a short polling window so they surface.
                cache.forceRefreshUntil = Date.now() + FORCE_REFRESH_WINDOW_MS
                actions.loadRuns(null)
            } catch (e: any) {
                lemonToast.error(`Failed to enqueue re-run: ${e?.detail ?? e?.message ?? String(e)}`)
            }
        },
    })),

    actionToUrl(({ values, props }) => {
        // Per-job scoped tables (batch view) don't own the URL — several can mount on one
        // scene and they'd clobber the shared `inv_*` params. Only the flat list syncs.
        if (props.parentRunId) {
            return {}
        }
        const buildUrl = (): [
            string,
            Record<string, string | undefined>,
            Record<string, string>,
            { replace: true },
        ] => [
            router.values.location.pathname,
            { ...router.values.searchParams, ...filtersToSearchParams(values.filters) },
            router.values.hashParams,
            { replace: true },
        ]
        return {
            setFilters: buildUrl,
            resetFilters: buildUrl,
        }
    }),

    urlToAction(({ actions, values, props }) => {
        const handleSearch = (_: any, searchParams: Record<string, string | undefined>): void => {
            // Per-job scoped tables (batch view) don't own the URL — several can mount on one
            // scene and they'd clobber the shared `inv_*` params. Only the flat list syncs.
            if (props.parentRunId) {
                return
            }
            const next = searchParamsToFilters(searchParams)
            // Diff against current state to avoid looping with actionToUrl.
            const changed = Object.entries(next).some(
                ([key, value]) =>
                    JSON.stringify(value) !== JSON.stringify(values.filters[key as keyof HogInvocationsFilters])
            )
            if (changed) {
                actions.setFilters(next)
            }
        }
        return {
            '*': handleSearch,
        }
    }),
])
