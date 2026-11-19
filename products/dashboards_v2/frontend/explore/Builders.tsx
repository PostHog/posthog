import { createContext, useContext, useEffect, useMemo, useState } from 'react'

import { IconEye, IconHide, IconMinus, IconSearch, IconX } from '@posthog/icons'
import {
    Badge,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Input,
} from '@posthog/quill'

import { compactNumber } from 'lib/utils/numbers'

import { FieldRow, OptionSelect, Segmented } from '../editor/OptionsForm'
import { VariablePicker, type VariablePickerProps } from '../editor/VariablePicker'
import { api, pj, runQuery, useMetricUsage, useUsage } from '../lib/api'
import { pushRecent, readStored } from '../lib/hooks'
import { keepPreviousData, useQueries, useQuery, type QueryOptions } from '../lib/useQuery'
import {
    AGGS,
    DEFAULT_FACETS,
    filterValues,
    withOp,
    RANGES,
    seriesCountsQuery,
    toggleValue,
    defaultMetric,
    facetsQuery,
    FILTER_OPS,
    metricKind,
    OPTIONS,
    type Builder,
    type Filter,
    type FilterOp,
    type LogsMode,
    type LogsState,
    type MetricRange,
    type MetricsState,
    type TracesMode,
    type TracesState,
    durationsQuery,
    DURATION_EDGES,
    TRACE_FACETS,
    traceFacetsQuery,
    withSpanFilter,
    hexId,
    storedId,
    withFilter,
} from './build'
import { EventsBuilder } from './EventsBuilder'
import { applyNav, describeNav, introspectNav, useIntrospectPicker, type IntrospectPick } from './Introspect'

type FoundOptions = { options: string[]; total?: number; details?: Record<string, string> }

export const fetchOptions = (
    projectId: string,
    language: 'promql' | 'hogql',
    query: string,
    search?: string
): Promise<FoundOptions> =>
    api<FoundOptions>(`${pj(projectId)}/variables/options`, {
        method: 'POST',
        body: JSON.stringify({
            variable: { name: 'opt', type: 'query', language, query },
            variables: {},
            time: { from: 'now-1h', to: 'now' },
            search,
        }),
    })

const ProjectContext = createContext('')
export const ProjectScope = ProjectContext.Provider
export const useProjectId = (): string => useContext(ProjectContext)
const TimeContext = createContext({ from: 'now-1h', to: 'now' })
export const BuilderTime = TimeContext.Provider

export function useOptions(
    projectId: string,
    language: 'promql' | 'hogql',
    query: string | undefined,
    searchQuery?: (q: string) => string
): Options {
    const r = useQuery({
        queryKey: ['explore-options', projectId, language, query],
        enabled: !!query,
        staleTime: 5 * 60_000,
        queryFn: () => fetchOptions(projectId, language, query!),
    })
    const options = r.data?.options
    const limit = Number(/\bLIMIT\s+(\d+)\s*$/i.exec(query ?? '')?.[1] ?? Infinity)
    const serverHasMore = (r.data?.total ?? 0) > (options?.length ?? 0)
    const queryCut = !!searchQuery && (options?.length ?? 0) >= limit
    const search: Options['search'] =
        !options || (!serverHasMore && !queryCut)
            ? {}
            : serverHasMore
              ? {
                    total: r.data!.total,
                    onSearch: (q: string) => fetchOptions(projectId, language, query!, q).then((x) => x.options),
                }
              : {
                    total: Infinity,
                    onSearch: (q: string) => fetchOptions(projectId, language, searchQuery!(q)).then((x) => x.options),
                }
    return { data: options, details: r.data?.details, isLoading: r.isLoading, search }
}
type Options = {
    data: string[] | undefined
    details: Record<string, string> | undefined
    isLoading: boolean
    search: { total?: number; onSearch?: (q: string) => Promise<string[]> }
}

function useFacetsShown(): readonly [boolean, (v: boolean) => void] {
    const [shown, setShown] = useState(() => readStored('dashboards-v2.facets.shown', true))
    const set = (v: boolean): void => {
        localStorage.setItem('dashboards-v2.facets.shown', JSON.stringify(v))
        setShown(v)
    }
    return [shown, set] as const
}
function FacetsSwitch({ shown, onChange }: { shown: boolean; onChange: (v: boolean) => void }): React.JSX.Element {
    return (
        <button
            type="button"
            className="ml-auto flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            aria-pressed={shown}
            title={shown ? 'Hide the facet counts' : 'Show the facet counts'}
            data-attr="dashboard-v2-facets-toggle"
            onClick={() => onChange(!shown)}
        >
            {shown ? <IconHide className="size-3.5" /> : <IconEye className="size-3.5" />}
            {shown ? 'Hide' : 'Show'}
        </button>
    )
}

export function Picker({ kind, onChange, ...props }: VariablePickerProps & { kind: string }): React.JSX.Element {
    const projectId = useProjectId()
    const key = `dashboards-v2.recent.${projectId}.${kind}`
    const [recent, setRecent] = useState(() => readStored<string[]>(key, []))
    const pick = (next: string[]): void => {
        const added = next.filter((v) => !props.value.includes(v))
        if (added.length) {
            setRecent(pushRecent(key, added, 6))
        }
        onChange(next)
    }
    return <VariablePicker {...props} recent={recent} onChange={pick} />
}

export function QueryBuilder({
    projectId,
    state: b,
    empty,
    onChange: set,
}: {
    projectId: string
    state: Builder
    empty: boolean
    onChange: (b: Builder) => void
}): React.JSX.Element {
    useEffect(() => {
        if ((b.source === 'logs' || b.source === 'traces') && empty) {
            set(b)
        }
    }, [b.source])
    return (
        <ProjectScope value={projectId}>
            <div className="flex flex-col gap-3">
                {b.source === 'events' ? (
                    <EventsBuilder projectId={projectId} state={b} onChange={(s) => set({ ...s, source: 'events' })} />
                ) : b.source === 'logs' ? (
                    <LogsBuilder state={b} onChange={(s) => set({ ...s, source: 'logs' })} />
                ) : b.source === 'traces' ? (
                    <TracesBuilder state={b} onChange={(s) => set({ ...s, source: 'traces' })} />
                ) : (
                    <MetricsBuilder
                        projectId={projectId}
                        state={b}
                        onChange={(s) => set({ ...s, source: 'metrics' })}
                    />
                )}
            </div>
        </ProjectScope>
    )
}

export function MetricsBuilder({
    projectId,
    state,
    onChange,
}: {
    projectId: string
    state: MetricsState
    onChange: (s: MetricsState) => void
}): React.JSX.Element {
    const [facetsShown, setFacetsShown] = useFacetsShown()
    const names = useOptions(projectId, 'promql', OPTIONS.metrics)
    const usage = useUsage(projectId)
    const metric = state.metric
    useEffect(() => {
        if (!metric && names.data?.length && !usage.isLoading) {
            onChange({ ...state, metric: defaultMetric(names.data, usage.data?.metrics) })
        }
    }, [metric, names.data, usage.isLoading])
    const metricUsage = useMetricUsage(projectId, metric)
    const labelCounts =
        metricUsage.data && Object.keys(metricUsage.data.labels).length ? metricUsage.data.labels : usage.data?.labels
    const labels = useOptions(projectId, 'promql', metric && OPTIONS.labels(metric))
    const kind = metricKind(metric ?? '')
    const aggs = AGGS[kind]
    const agg = aggs.some((a) => a.value === state.agg) ? state.agg! : aggs[0]!.value
    const labelKeys = (labels.data ?? []).filter((l) => l !== 'le' && l !== '__name__')
    const facetKeys =
        state.facets ?? [...labelKeys].sort((a, b) => (labelCounts?.[b] ?? 0) - (labelCounts?.[a] ?? 0)).slice(0, 5)
    const introspect = useIntrospectPicker(projectId)
    const asBuilder = { ...state, source: 'metrics' as const }
    const use = pickInto((n) => onChange(stateOf(applyNav(asBuilder, n))))
    return (
        <ProjectScope value={projectId}>
            <div className="flex flex-col gap-2">
                <FieldRow side label="Metric">
                    <Picker
                        kind="metric"
                        popular={usage.data?.metrics}
                        label="Metric"
                        {...names.search}
                        options={names.data ?? []}
                        loading={names.isLoading}
                        placeholder={
                            names.isLoading
                                ? 'Finding metrics…'
                                : names.data?.length === 0
                                  ? 'No metrics in this project'
                                  : 'Pick a metric'
                        }
                        value={metric ? [metric] : []}
                        onChange={([m]) => onChange({ metric: m })}
                        onBrowse={introspect.open({ source: 'metrics', conds: [] }, use)}
                    />
                    {metric && (
                        <Badge
                            variant="default"
                            className="text-[10px] font-normal"
                            title="From the metric name: counters are charted as a rate, histograms as a quantile"
                        >
                            {kind}
                        </Badge>
                    )}
                </FieldRow>
                <FieldRow side label="Show">
                    <OptionSelect
                        className="h-7 w-32 text-xs"
                        options={aggs.map((a) => [a.value, a.label] as const)}
                        value={agg}
                        onChange={(v) => onChange({ ...state, agg: v })}
                    />
                    {kind === 'counter' && (
                        <>
                            <span className="text-xs text-muted-foreground">of</span>
                            <Segmented
                                className="h-7"
                                options={RANGES}
                                value={state.range ?? 'rate'}
                                onChange={(r) =>
                                    onChange({ ...state, range: r === 'rate' ? undefined : (r as MetricRange) })
                                }
                            />
                        </>
                    )}
                </FieldRow>
                {agg !== 'none' && (
                    <FieldRow side label="By">
                        <Picker
                            kind="label"
                            popular={labelCounts}
                            label="Group by"
                            multi
                            {...labels.search}
                            options={labels.data ?? []}
                            loading={labels.isLoading}
                            placeholder="Nothing"
                            value={state.by ?? []}
                            onChange={(by) => onChange({ ...state, by })}
                            onBrowse={introspect.open({ ...introspectNav(asBuilder)!, attr: undefined }, use)}
                        />
                    </FieldRow>
                )}
                <FieldRow side label="Where">
                    <Filters
                        state={state.filters ?? []}
                        keys={labels}
                        keyCounts={labelCounts}
                        valueCounts={usage.data?.values}
                        values={(k) => metric && OPTIONS.labelValues(metric, k)}
                        countsQuery={(k) => seriesCountsQuery(state, k, 200)}
                        multi
                        language="promql"
                        onChange={(filters) => onChange({ ...state, filters })}
                    />
                </FieldRow>
                {metric && (
                    <>
                        <FieldRow side label="Facets">
                            {facetsShown && (
                                <Picker
                                    kind="metrics-facet"
                                    popular={labelCounts}
                                    label="Facets"
                                    multi
                                    {...labels.search}
                                    options={labelKeys}
                                    loading={labels.isLoading}
                                    placeholder="None"
                                    value={facetKeys}
                                    onChange={(f) => onChange({ ...state, facets: f })}
                                />
                            )}
                            <FacetsSwitch shown={facetsShown} onChange={setFacetsShown} />
                        </FieldRow>
                        {facetsShown && <MetricsFacets state={state} keys={facetKeys} onChange={onChange} />}
                    </>
                )}
            </div>
            {introspect.dialog}
        </ProjectScope>
    )
}

function LogsBuilder({ state, onChange }: { state: LogsState; onChange: (s: LogsState) => void }): React.JSX.Element {
    const [facetsShown, setFacetsShown] = useFacetsShown()
    const projectId = useProjectId()
    const usage = useUsage(projectId)
    const services = useOptions(projectId, 'hogql', OPTIONS.services(), OPTIONS.services)
    const levels = useOptions(projectId, 'hogql', OPTIONS.levels)
    const keys = useOptions(projectId, 'hogql', OPTIONS.attributeKeys(state), (q) => OPTIONS.attributeKeys(state, q))
    const resourceKeys = useOptions(projectId, 'hogql', OPTIONS.resourceKeys(state))
    const introspect = useIntrospectPicker(projectId)
    const asBuilder = { ...state, source: 'logs' as const }
    useEffect(() => {
        const r = new Set(resourceKeys.data ?? [])
        if (state.filters?.some((f) => !f.resource && r.has(f.key))) {
            onChange({ ...state, filters: state.filters.map((f) => (r.has(f.key) ? { ...f, resource: true } : f)) })
        }
    }, [resourceKeys.data, state.filters])
    const [search, setSearch] = useState(state.search ?? '')
    useEffect(() => setSearch(state.search ?? ''), [state.search])
    useEffect(() => {
        if (search === (state.search ?? '')) {
            return
        }
        const t = setTimeout(() => onChange({ ...state, search: search || undefined }), 500)
        return () => clearTimeout(t)
    }, [search])
    return (
        <div className="flex flex-col gap-2">
            <FieldRow side label="Service">
                <Picker
                    kind="service"
                    popular={usage.data?.services}
                    label="Service"
                    multi
                    {...services.search}
                    options={services.data ?? []}
                    loading={services.isLoading}
                    placeholder="All"
                    value={state.services ?? []}
                    onChange={(s) => onChange({ ...state, services: s })}
                    onBrowse={introspect.open(
                        { ...introspectNav(asBuilder)!, entity: undefined, attr: undefined },
                        pickInto((n) => onChange(stateOf(applyNav(asBuilder, n))))
                    )}
                />
            </FieldRow>
            {!(facetsShown && (state.facets ?? DEFAULT_FACETS).includes('severity_text')) && (
                <FieldRow side label="Level">
                    <VariablePicker
                        label="Level"
                        multi
                        options={levels.data ?? []}
                        loading={levels.isLoading}
                        placeholder="All"
                        value={state.levels ?? []}
                        onChange={(l) => onChange({ ...state, levels: l })}
                    />
                </FieldRow>
            )}
            <FieldRow side label="Search">
                <div className="relative flex-1">
                    <IconSearch className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                    <Input
                        className="h-7 pl-7 text-xs"
                        placeholder="Text in the log line"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && onChange({ ...state, search: search || undefined })}
                    />
                </div>
            </FieldRow>
            <FieldRow side label="Where">
                <Filters
                    state={state.filters ?? []}
                    keys={keys}
                    keyCounts={usage.data?.attributes}
                    valueCounts={usage.data?.values}
                    values={(k, q) => OPTIONS.attributeValues(state, k, q)}
                    isResource={(k) => !!resourceKeys.data?.includes(k)}
                    language="hogql"
                    onChange={(filters) => onChange({ ...state, filters })}
                />
            </FieldRow>
            <FieldRow side label="Show">
                <Segmented
                    options={[
                        ['lines', 'Lines'],
                        ['patterns', 'Patterns'],
                        ['group', 'Group'],
                    ]}
                    value={state.mode ?? 'lines'}
                    onChange={(m) => onChange({ ...state, mode: m === 'lines' ? undefined : (m as LogsMode) })}
                />
                {(state.mode ?? 'lines') === 'lines' && (
                    <Segmented
                        options={[
                            ['desc', 'Newest first'],
                            ['asc', 'Oldest first'],
                        ]}
                        value={state.order ?? 'desc'}
                        onChange={(o) => onChange({ ...state, order: o === 'asc' ? 'asc' : undefined })}
                    />
                )}
            </FieldRow>
            {state.mode === 'group' && (
                <FieldRow side label="By">
                    <Picker
                        kind="logs-group"
                        popular={usage.data?.attributes}
                        label="Group by (up to 4)"
                        multi
                        {...keys.search}
                        options={['service_name', 'severity_text', ...(keys.data ?? [])]}
                        loading={keys.isLoading}
                        placeholder="service_name"
                        value={state.groupBy ?? []}
                        onChange={(g) => onChange({ ...state, groupBy: g.length ? g.slice(0, 4) : undefined })}
                    />
                </FieldRow>
            )}
            <FieldRow side label="Volume">
                <Segmented
                    options={[
                        ['level', 'By level'],
                        ['service', 'By service'],
                    ]}
                    value={state.volumeBy ?? 'level'}
                    onChange={(v) => onChange({ ...state, volumeBy: v === 'service' ? 'service' : undefined })}
                />
            </FieldRow>
            <FieldRow side label="Facets">
                {facetsShown && (
                    <Picker
                        kind="logs-facet"
                        popular={usage.data?.attributes}
                        label="Facets"
                        multi
                        {...resourceKeys.search}
                        options={[...new Set([...DEFAULT_FACETS, ...(resourceKeys.data ?? [])])]}
                        loading={resourceKeys.isLoading}
                        placeholder="None"
                        value={state.facets ?? DEFAULT_FACETS}
                        onChange={(f) => onChange({ ...state, facets: f })}
                    />
                )}
                <FacetsSwitch shown={facetsShown} onChange={setFacetsShown} />
            </FieldRow>
            {facetsShown && <LogsFacets state={state} onChange={onChange} />}
            {introspect.dialog}
        </div>
    )
}

const pickInto = (apply: IntrospectPick['apply']): IntrospectPick => ({
    action: 'Use',
    describe: (n) => (n.entity !== undefined ? `Use ${describeNav(n)}` : undefined),
    hint: 'Point at one, or open it to narrow it and pick a breakdown',
    apply,
})
const stateOf = <B extends { source: string }>({ source: _, ...s }: B): Omit<B, 'source'> => s

function TracesBuilder({
    state,
    onChange,
}: {
    state: TracesState
    onChange: (s: TracesState) => void
}): React.JSX.Element {
    const [facetsShown, setFacetsShown] = useFacetsShown()
    const projectId = useProjectId()
    const services = useOptions(projectId, 'hogql', OPTIONS.spanServices(), OPTIONS.spanServices)
    const names = useOptions(projectId, 'hogql', OPTIONS.spanNames(state), (q) => OPTIONS.spanNames(state, q))
    const keys = useOptions(projectId, 'hogql', OPTIONS.spanKeys(state), (q) => OPTIONS.spanKeys(state, q))
    const resourceKeys = useOptions(projectId, 'hogql', OPTIONS.spanResourceKeys(state))
    const [id, setId] = useState(state.traceId ? hexId(storedId(state.traceId)) : '')
    useEffect(() => setId(state.traceId ? hexId(storedId(state.traceId)) : ''), [state.traceId])
    const commitId = (): void => {
        const t = id.trim()
        if (t !== (state.traceId ? hexId(storedId(state.traceId)) : '')) {
            const { traceId: _t, ...rest } = state
            onChange(t ? { ...state, traceId: storedId(t) } : rest)
        }
    }
    const traceRow = (
        <FieldRow side label="Trace">
            <div className="relative flex-1">
                <IconSearch className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                    className="h-7 pl-7 font-mono text-xs"
                    placeholder="Paste a trace id to open it"
                    data-attr="dashboard-v2-trace-id"
                    value={id}
                    onChange={(e) => setId(e.target.value)}
                    onBlur={commitId}
                    onKeyDown={(e) => e.key === 'Enter' && commitId()}
                />
            </div>
            {state.traceId && (
                <Button
                    variant="default"
                    size="icon-xs"
                    title="Back to all traces"
                    onClick={() => {
                        const { traceId: _t, ...rest } = state
                        onChange(rest)
                    }}
                >
                    <IconX className="size-3" />
                </Button>
            )}
        </FieldRow>
    )
    if (state.traceId) {
        return <div className="flex flex-col gap-2">{traceRow}</div>
    }
    return (
        <div className="flex flex-col gap-2">
            <FieldRow side label="Service">
                <Picker
                    kind="span-service"
                    label="Service"
                    multi
                    {...services.search}
                    options={services.data ?? []}
                    loading={services.isLoading}
                    placeholder="All"
                    value={state.services ?? []}
                    onChange={(v) => onChange({ ...state, services: v.length ? v : undefined })}
                />
            </FieldRow>
            <FieldRow side label="Span name">
                <Picker
                    kind="span-name"
                    label="Span name"
                    multi
                    {...names.search}
                    options={names.data ?? []}
                    loading={names.isLoading}
                    placeholder="All"
                    value={state.names ?? []}
                    onChange={(v) => onChange({ ...state, names: v.length ? v : undefined })}
                />
            </FieldRow>
            <FieldRow side label="Status">
                <Segmented
                    options={[
                        ['all', 'All'],
                        ['error', 'Errors'],
                        ['ok', 'Not errors'],
                    ]}
                    value={state.status ?? 'all'}
                    onChange={(v) => onChange({ ...state, status: v === 'all' ? undefined : (v as 'error' | 'ok') })}
                />
            </FieldRow>
            <FieldRow side label="Duration">
                <MsInput label="At least" value={state.minMs} onChange={(minMs) => onChange({ ...state, minMs })} />
                <span className="text-xs text-muted-foreground">to</span>
                <MsInput label="Under" value={state.maxMs} onChange={(maxMs) => onChange({ ...state, maxMs })} />
                <span className="text-xs text-muted-foreground">ms</span>
            </FieldRow>
            <DurationFacet state={state} onChange={onChange} />
            <FieldRow side label="Volume">
                <Segmented
                    options={[
                        ['status', 'By status'],
                        ['service', 'By service'],
                    ]}
                    value={state.volumeBy ?? 'status'}
                    onChange={(v) => onChange({ ...state, volumeBy: v === 'service' ? 'service' : undefined })}
                />
            </FieldRow>
            <FieldRow side label="Where">
                <Filters
                    state={state.filters ?? []}
                    keys={keys}
                    values={(k, q) => OPTIONS.spanValues(state, k, q)}
                    isResource={(k) => !!resourceKeys.data?.includes(k)}
                    language="hogql"
                    onChange={(filters) => onChange({ ...state, filters })}
                />
            </FieldRow>
            <FieldRow side label="Show">
                <Segmented
                    options={[
                        ['traces', 'Traces'],
                        ['spans', 'Spans'],
                        ['operations', 'Operations'],
                    ]}
                    value={state.mode ?? 'traces'}
                    onChange={(v) => onChange({ ...state, mode: v === 'traces' ? undefined : (v as TracesMode) })}
                />
                <Segmented
                    options={
                        state.mode === 'operations'
                            ? [
                                  ['time', 'Most time'],
                                  ['duration', 'Slowest p95'],
                              ]
                            : [
                                  ['time', 'Newest first'],
                                  ['duration', 'Slowest first'],
                              ]
                    }
                    value={state.order ?? 'time'}
                    onChange={(v) => onChange({ ...state, order: v === 'duration' ? 'duration' : undefined })}
                />
            </FieldRow>
            {state.mode === 'operations' && (
                <FieldRow side label="Impact">
                    <label
                        className="flex items-center gap-1.5 text-xs"
                        title="Reads every span's attributes: slower on big projects"
                    >
                        <input
                            type="checkbox"
                            className="size-3"
                            checked={!!state.impact}
                            onChange={(e) => onChange({ ...state, impact: e.target.checked || undefined })}
                        />
                        Count the sessions and people behind each operation
                    </label>
                </FieldRow>
            )}
            {traceRow}
            <FieldRow side label="Facets">
                {facetsShown && (
                    <Picker
                        kind="trace-facet"
                        label="Facets"
                        multi
                        {...keys.search}
                        options={[...new Set([...TRACE_FACETS, ...(keys.data ?? [])])]}
                        loading={keys.isLoading}
                        placeholder="None"
                        value={state.facets ?? TRACE_FACETS}
                        onChange={(f) => onChange({ ...state, facets: f })}
                    />
                )}
                <FacetsSwitch shown={facetsShown} onChange={setFacetsShown} />
            </FieldRow>
            {facetsShown && <TracesFacets state={state} onChange={onChange} />}
        </div>
    )
}

function Filters({
    state,
    keys,
    keyCounts,
    valueCounts,
    values,
    isResource,
    countsQuery,
    multi,
    language,
    onChange,
}: {
    state: Filter[]
    keys: Options
    countsQuery?: (k: string) => string | undefined
    multi?: boolean
    keyCounts?: Record<string, number>
    valueCounts?: Record<string, Record<string, number>>
    values: (k: string, q?: string) => string | undefined
    isResource?: (k: string) => boolean
    language: 'promql' | 'hogql'
    onChange: (f: Filter[]) => void
}): React.JSX.Element {
    const set = (i: number, f: Partial<Filter>): void => onChange(state.map((x, j) => (j === i ? { ...x, ...f } : x)))
    return (
        <>
            {state.map((f, i) => (
                <FilterChip
                    key={i}
                    f={f}
                    keys={keys}
                    keyCounts={keyCounts}
                    isResource={isResource}
                    popular={valueCounts?.[f.key]}
                    values={(q) => values(f.key, q)}
                    countsQuery={countsQuery?.(f.key)}
                    multi={multi}
                    language={language}
                    onChange={(p) => set(i, p)}
                    onRemove={() => onChange(state.filter((_, j) => j !== i))}
                />
            ))}
            <Picker
                kind={`${language}-key`}
                popular={keyCounts}
                label="Filter on"
                {...keys.search}
                options={keys.data ?? []}
                loading={keys.isLoading}
                placeholder="+ Filter"
                value={[]}
                onChange={([k]) =>
                    k &&
                    onChange([...state, { key: k, op: '=', value: '', ...(isResource?.(k) && { resource: true }) }])
                }
            />
        </>
    )
}

const PART = 'flex max-w-48 items-center gap-0.5 rounded px-1 py-0.5 hover:bg-fill-hover'
const OP_LABEL = (op: FilterOp, multi?: boolean): string =>
    ({
        '=': multi ? 'is any of' : 'equals',
        '!=': multi ? 'is none of' : 'not equals',
        '=~': 'matches regex',
        '!~': "doesn't match regex",
    })[op]

function FilterChip({
    f,
    keys,
    keyCounts,
    isResource,
    popular,
    values,
    countsQuery,
    multi,
    language,
    onChange,
    onRemove,
}: {
    f: Filter
    keys: Options
    keyCounts?: Record<string, number>
    isResource?: (k: string) => boolean
    popular?: Record<string, number>
    values: (q?: string) => string | undefined
    countsQuery?: string
    multi?: boolean
    language: 'promql' | 'hogql'
    onChange: (f: Partial<Filter>) => void
    onRemove: () => void
}): React.JSX.Element {
    const projectId = useProjectId()
    const time = useContext(TimeContext)
    const opts = useOptions(projectId, language, values(), (q) => values(q)!)
    const counted = useQuery(seriesCounts(projectId, time, countsQuery, f.key)).data
    const counts = counted && Object.fromEntries(counted.map((c) => [c.value, c.n]))
    const options = counts
        ? [...counted.map((c) => c.value), ...(opts.data ?? []).filter((v) => !(v in counts))]
        : (opts.data ?? [])
    const anyOf = multi ? filterValues(f) : undefined
    const shown = anyOf ? anyOf.join(', ') : f.value
    const valueTrigger = (
        <>
            <span className={`truncate ${shown ? '' : 'text-muted-foreground'}`} title={shown}>
                {shown || (f.op.includes('~') ? 'regex…' : 'value…')}
            </span>
        </>
    )
    return (
        <div className="flex items-center gap-0.5 rounded-md border bg-muted py-0.5 pl-0.5 text-xs">
            <Picker
                kind={`${language}-key`}
                popular={keyCounts}
                label="Filter on"
                {...keys.search}
                options={keys.data ?? []}
                loading={keys.isLoading}
                value={[f.key]}
                className={`${PART} font-mono`}
                trigger={
                    <>
                        <span className="truncate" title={f.key}>
                            {f.key}
                        </span>
                    </>
                }
                onChange={([k]) =>
                    k &&
                    k !== f.key &&
                    onChange({ key: k, value: '', values: undefined, resource: isResource?.(k) || undefined })
                }
            />
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={<button className={`${PART} font-mono text-muted-foreground`} />}
                    title={OP_LABEL(f.op, multi)}
                    data-attr="dashboard-v2-filter-op"
                >
                    {f.op}
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                    {FILTER_OPS.map((op) => (
                        <DropdownMenuItem
                            key={op}
                            onClick={() =>
                                onChange(multi ? { values: undefined, resource: undefined, ...withOp(f, op) } : { op })
                            }
                        >
                            <span className="w-5 font-mono">{op}</span>
                            {OP_LABEL(op, multi)}
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuContent>
            </DropdownMenu>
            {anyOf ? (
                <Picker
                    kind={`value.${f.key}`}
                    popular={counts ? undefined : popular}
                    counts={counts}
                    label={`${f.key} (${OP_LABEL(f.op, true)})`}
                    multi
                    {...opts.search}
                    options={options}
                    loading={opts.isLoading}
                    value={anyOf}
                    className={PART}
                    trigger={valueTrigger}
                    onChange={(vs) => onChange({ value: vs[0] ?? '', values: vs.length > 1 ? vs : undefined })}
                />
            ) : (
                <Picker
                    kind={`value.${f.key}`}
                    popular={counts ? undefined : popular}
                    counts={counts}
                    label={f.key}
                    creatable
                    {...opts.search}
                    options={options}
                    loading={opts.isLoading}
                    value={f.value ? [f.value] : []}
                    className={PART}
                    trigger={valueTrigger}
                    onChange={([v]) => onChange({ value: v ?? '' })}
                />
            )}
            <Button variant="default" size="icon-xs" aria-label={`Remove the ${f.key} filter`} onClick={onRemove}>
                <IconX className="size-3" />
            </Button>
        </div>
    )
}

const FACET_LABEL: Record<string, string> = { severity_text: 'Level', service_name: 'Service', name: 'Span name' }
const LEVEL_BAR: Record<string, string> = {
    error: 'text-destructive-foreground',
    fatal: 'text-destructive-foreground',
    warn: 'text-warning-foreground',
    warning: 'text-warning-foreground',
    info: 'text-info-foreground',
}
const nf = new Intl.NumberFormat()

type FacetValue = { value: string; n: number; resource: boolean }
type FacetData = { groups: [string, FacetValue[]][]; isLoading: boolean; isFetching: boolean; error?: string }

function useHogqlFacets(query?: string): FacetData {
    const projectId = useProjectId()
    const time = useContext(TimeContext)
    const r = useQuery({
        queryKey: ['facets', projectId, query, time.from, time.to],
        enabled: !!query,
        staleTime: 60_000,
        placeholderData: keepPreviousData,
        queryFn: ({ signal }) =>
            runQuery({
                signal,
                projectId,
                target: { refId: 'F', language: 'hogql', format: 'table', query: query! },
                time,
                variables: {},
            }),
    })
    const frame = r.data?.frames[0]
    const groups = useMemo(() => {
        if (!frame) {
            return []
        }
        const col = (n: string): unknown[] => frame.fields.find((f) => f.name === n)?.values ?? []
        const [facet, value, n, resource] = ['facet', 'value', 'n', 'resource'].map(col) as unknown[][]
        const out = new Map<string, FacetValue[]>()
        facet!.forEach((k, i) => {
            const list = out.get(String(k)) ?? []
            list.push({ value: String(value![i] ?? ''), n: Number(n![i] ?? 0), resource: !!Number(resource![i]) })
            out.set(String(k), list)
        })
        return [...out]
    }, [frame])
    return { groups, isLoading: r.isLoading, isFetching: r.isFetching, error: r.data?.error }
}

const seriesCounts = (
    projectId: string,
    time: { from: string; to: string },
    query: string | undefined,
    key: string
): QueryOptions<FacetValue[]> => ({
    queryKey: ['series-counts', projectId, query, time.from, time.to],
    enabled: !!query,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
    queryFn: async ({ signal }): Promise<FacetValue[]> => {
        const r = await runQuery({
            signal,
            projectId,
            target: { refId: 'F', language: 'promql', instant: true, query: query! },
            time,
            variables: {},
        })
        if (r.error) {
            throw new Error(r.error)
        }
        return r.frames
            .map((f) => {
                const v = f.fields.find((x) => x.labels) ?? f.fields.at(-1)
                return { value: v?.labels?.[key] ?? '', n: Math.round(Number(v?.values[0] ?? 0)), resource: false }
            })
            .sort((a, b) => b.n - a.n)
    },
})

function MetricsFacets({
    state,
    keys,
    onChange,
}: {
    state: MetricsState
    keys: string[]
    onChange: (s: MetricsState) => void
}): React.JSX.Element {
    const projectId = useProjectId()
    const time = useContext(TimeContext)
    const rs = useQueries({ queries: keys.map((k) => seriesCounts(projectId, time, seriesCountsQuery(state, k), k)) })
    const has = (k: string, v: string, neg: boolean): boolean =>
        !!state.filters?.some(
            (f) => f.key === k && (f.op === '!=' || f.op === '!~') === neg && filterValues(f)?.includes(v)
        )
    const error = rs.find((r) => r.error)?.error
    return (
        <FacetList
            dataAttr="dashboard-v2-metrics-facets"
            data={{
                groups: keys.map((k, i) => [k, rs[i]?.data ?? []] as [string, FacetValue[]]),
                isLoading: rs.some((r) => r.isLoading),
                isFetching: rs.some((r) => r.isFetching),
                error: error?.message,
            }}
            isOn={(k, v) => has(k, v, false)}
            isOut={(k, v) => has(k, v, true)}
            onPick={(k, v, _, op) =>
                onChange({ ...state, filters: toggleValue(state.filters ?? [], k, v, op === '!=') })
            }
            note="Series per value over the time range, every other filter applied."
        />
    )
}

function FacetList({
    data,
    isOn,
    isOut,
    onPick,
    color,
    note,
    dataAttr,
}: {
    data: FacetData
    isOn: (k: string, v: string) => boolean
    isOut: (k: string, v: string) => boolean
    onPick: (k: string, v: string, resource: boolean, op: '=' | '!=') => void
    color?: (k: string, v: string) => string | undefined
    note?: string
    dataAttr: string
}): React.JSX.Element {
    const { groups } = data
    if (data.error) {
        return <div className="text-xs text-destructive-foreground">Facet counts failed: {data.error}</div>
    }
    return (
        <div className={`flex flex-col gap-2 text-xs ${data.isFetching ? 'opacity-60' : ''}`} data-attr={dataAttr}>
            {data.isLoading && <div className="text-muted-foreground">Counting…</div>}
            {groups.map(([k, values]) => (
                <div key={k} className="flex flex-col">
                    <div
                        className={`truncate pb-0.5 text-[10px] font-semibold text-muted-foreground ${FACET_LABEL[k] ? 'uppercase tracking-wide' : 'font-mono'}`}
                        title={k}
                    >
                        {FACET_LABEL[k] ?? k}
                    </div>
                    {values.map(({ value: v, n, resource }) => {
                        const out = isOut(k, v)
                        const c = color?.(k, v)
                        return (
                            <div
                                key={v}
                                className="group/facet flex items-center gap-1.5 rounded px-0.5 hover:bg-fill-hover"
                            >
                                <input
                                    type="checkbox"
                                    className="size-3 shrink-0"
                                    checked={isOn(k, v)}
                                    aria-label={`${FACET_LABEL[k] ?? k} ${v || '(empty)'}`}
                                    onChange={() => onPick(k, v, resource, '=')}
                                />
                                {c && <span className={`h-3 w-0.5 shrink-0 rounded-full bg-current ${c}`} />}
                                <span
                                    className={`min-w-0 flex-1 truncate ${out ? 'line-through opacity-60' : ''}`}
                                    title={v}
                                >
                                    {v || '(empty)'}
                                </span>
                                <button
                                    type="button"
                                    className={`shrink-0 ${out ? 'text-foreground' : 'text-muted-foreground opacity-0 group-hover/facet:opacity-100'} hover:text-foreground`}
                                    title={out ? 'Stop excluding' : `Exclude ${v || '(empty)'}`}
                                    onClick={() => onPick(k, v, resource, '!=')}
                                >
                                    <IconMinus className="size-3" />
                                </button>
                                <span className="shrink-0 tabular-nums text-muted-foreground" title={nf.format(n)}>
                                    {compactNumber(n)}
                                </span>
                            </div>
                        )
                    })}
                </div>
            ))}
            {note && <div className="text-[10px] text-muted-foreground">{note}</div>}
        </div>
    )
}

function pickFacet<S extends { filters?: Filter[] }>(
    s: S,
    lists: Record<string, keyof S>,
    merge: (s: S, f: Filter) => S,
    k: string,
    v: string,
    resource: boolean,
    op: '=' | '!='
): S {
    const list = lists[k]
    if (list && op === '=') {
        const cur = (s[list] as string[] | undefined) ?? []
        return { ...s, [list]: cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v] }
    }
    const on = s.filters?.find((f) => f.key === k && f.value === v)
    if (on?.op === op) {
        return { ...s, filters: s.filters!.filter((f) => f !== on) }
    }
    return merge(s, { key: k, op, value: v, ...(resource && !list ? { resource: true } : {}) })
}

const LOG_LISTS = { severity_text: 'levels', service_name: 'services' } as const
function LogsFacets({ state, onChange }: { state: LogsState; onChange: (s: LogsState) => void }): React.JSX.Element {
    const filterOf = (k: string, v: string): Filter | undefined =>
        state.filters?.find((f) => f.key === k && f.value === v)
    const list = (k: string): 'levels' | 'services' => LOG_LISTS[k as keyof typeof LOG_LISTS]
    const unseen = !!state.search?.trim() || !!state.filters?.some((f) => f.value && !f.resource && !list(f.key))
    return (
        <FacetList
            dataAttr="dashboard-v2-logs-facets"
            data={useHogqlFacets(facetsQuery(state))}
            isOn={(k, v) => (list(k) ? !!state[list(k)!]?.includes(v) : filterOf(k, v)?.op === '=')}
            isOut={(k, v) => filterOf(k, v)?.op === '!='}
            onPick={(k, v, resource, op) => onChange(pickFacet(state, LOG_LISTS, withFilter, k, v, resource, op))}
            color={(k, v) => (k === 'severity_text' ? LEVEL_BAR[v.toLowerCase()] : undefined)}
            note={unseen ? 'Counts leave out the text search and log-attribute filters.' : undefined}
        />
    )
}

const SPAN_LISTS = { service_name: 'services', name: 'names' } as const
function TracesFacets({
    state,
    onChange,
}: {
    state: TracesState
    onChange: (s: TracesState) => void
}): React.JSX.Element {
    const filterOf = (k: string, v: string): Filter | undefined =>
        state.filters?.find((f) => f.key === k && f.value === v)
    const list = (k: string): 'services' | 'names' => SPAN_LISTS[k as keyof typeof SPAN_LISTS]
    const unseen =
        !!state.names?.length ||
        !!state.status ||
        !!state.minMs ||
        !!state.maxMs ||
        !!state.filters?.some((f) => f.value && !f.resource)
    return (
        <FacetList
            dataAttr="dashboard-v2-traces-facets"
            data={useHogqlFacets(traceFacetsQuery(state))}
            isOn={(k, v) => (list(k) ? !!state[list(k)!]?.includes(v) : filterOf(k, v)?.op === '=')}
            isOut={(k, v) => filterOf(k, v)?.op === '!='}
            onPick={(k, v, resource, op) => onChange(pickFacet(state, SPAN_LISTS, withSpanFilter, k, v, resource, op))}
            note={`Span counts${unseen ? '; they leave out span names, status, duration and span-attribute filters' : ''}.`}
        />
    )
}

const msLabel = (ms: number): string => (ms >= 1000 ? `${ms / 1000}s` : `${ms}ms`)
function DurationFacet({
    state,
    onChange,
}: {
    state: TracesState
    onChange: (s: TracesState) => void
}): React.JSX.Element {
    const projectId = useProjectId()
    const time = useContext(TimeContext)
    const query = durationsQuery(state)
    const r = useQuery({
        queryKey: ['trace-durations', projectId, query, time.from, time.to],
        staleTime: 60_000,
        placeholderData: keepPreviousData,
        queryFn: ({ signal }) =>
            runQuery({
                signal,
                projectId,
                target: { refId: 'D', language: 'hogql', format: 'table', query },
                time,
                variables: {},
            }),
    })
    const frame = r.data?.frames[0]
    const counts = DURATION_EDGES.map(() => 0)
    const bucket = frame?.fields.find((f) => f.name === 'bucket')?.values ?? []
    const n = frame?.fields.find((f) => f.name === 'n')?.values ?? []
    bucket.forEach((b, i) => (counts[Number(b)] = Number(n[i] ?? 0)))
    const max = Math.max(1, ...counts)
    const lo = (i: number): number => DURATION_EDGES[i]!
    const hi = (i: number): number | undefined => DURATION_EDGES[i + 1]
    const inRange = (i: number): boolean =>
        (state.minMs !== undefined || state.maxMs !== undefined) &&
        lo(i) >= (state.minMs ?? 0) &&
        (state.maxMs === undefined || (hi(i) ?? Infinity) <= state.maxMs)
    const pick = (i: number, widen: boolean): void => {
        if (!widen && state.minMs === (lo(i) || undefined) && state.maxMs === hi(i)) {
            return onChange({ ...state, minMs: undefined, maxMs: undefined })
        }
        const from = widen ? Math.min(lo(i), state.minMs ?? lo(i)) : lo(i)
        const to = widen && state.maxMs !== undefined && (hi(i) ?? Infinity) < state.maxMs ? state.maxMs : hi(i)
        onChange({ ...state, minMs: from || undefined, maxMs: to })
    }
    if (r.data?.error) {
        return <div className="text-xs text-destructive-foreground">Duration counts failed: {r.data.error}</div>
    }
    return (
        <div
            className={`flex flex-col gap-0.5 ${r.isFetching ? 'opacity-60' : ''}`}
            data-attr="dashboard-v2-trace-durations"
        >
            <div className="flex h-12 items-end gap-px">
                {counts.map((c, i) => (
                    <button
                        key={i}
                        type="button"
                        className="flex-1 rounded-t-sm bg-primary"
                        style={{
                            height: `${Math.max(c ? 6 : 1, (Math.log1p(c) / Math.log1p(max)) * 100)}%`,
                            opacity: inRange(i) ? 1 : 0.35,
                        }}
                        title={`${hi(i) === undefined ? `${msLabel(lo(i))} or more` : `${msLabel(lo(i))} to ${msLabel(hi(i)!)}`}: ${nf.format(c)} (shift-click to widen)`}
                        onClick={(e) => pick(i, e.shiftKey)}
                    />
                ))}
            </div>
            <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>0</span>
                <span>100ms</span>
                <span>1s</span>
                <span>10s+</span>
            </div>
        </div>
    )
}

function MsInput({
    label,
    value,
    onChange,
}: {
    label: string
    value?: number
    onChange: (v?: number) => void
}): React.JSX.Element {
    const [text, setText] = useState(value ? String(value) : '')
    useEffect(() => setText(value ? String(value) : ''), [value])
    const commit = (): void => onChange(Number(text) > 0 ? Number(text) : undefined)
    return (
        <Input
            className="h-7 w-20 text-xs"
            inputMode="decimal"
            aria-label={label}
            placeholder={label === 'Under' ? 'any' : '0'}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => e.key === 'Enter' && commit()}
        />
    )
}
