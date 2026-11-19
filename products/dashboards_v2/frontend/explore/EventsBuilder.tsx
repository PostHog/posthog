import { useEffect, useState, type ComponentType, type ReactNode } from 'react'

import {
    IconFunnels,
    IconLifecycle,
    IconPencil,
    IconPlus,
    IconRetention,
    IconStack,
    IconStickiness,
    IconTarget,
    IconTrends,
    IconUserPaths,
    IconX,
} from '@posthog/icons'
import {
    Button,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Switch,
    cn,
} from '@posthog/quill'

import { short } from '../charts/format'
import { FieldRow, OptionSelect, Segmented } from '../editor/OptionsForm'
import {
    EVENT_OPTIONS,
    PATH_TYPES,
    eventNode,
    insightEvents,
    insightSource,
    newInsight,
    pathPointOptions,
    setInsightEvent,
    switchKind,
    withSource,
    type EventsState,
    type InsightKind,
} from './build'
import { Picker, ProjectScope, useOptions, useProjectId } from './Builders'
import { useIntrospectPicker } from './Introspect'
import { BreakdownPicker, PropertyFilters, useActionOptions, type PropertyFilter } from './PropertyFilter'

const KINDS: { kind: InsightKind; label: string; icon: ComponentType<{ className?: string }>; hint: string }[] = [
    { kind: 'TrendsQuery', label: 'Trends', icon: IconTrends, hint: 'How often events happen, over time' },
    {
        kind: 'FunnelsQuery',
        label: 'Funnel',
        icon: IconFunnels,
        hint: 'How many users get through a sequence of steps, and where they drop off',
    },
    {
        kind: 'RetentionQuery',
        label: 'Retention',
        icon: IconRetention,
        hint: 'How many users come back after they first do something',
    },
    {
        kind: 'StickinessQuery',
        label: 'Stickiness',
        icon: IconStickiness,
        hint: 'On how many days of a period users do something',
    },
    {
        kind: 'LifecycleQuery',
        label: 'Lifecycle',
        icon: IconLifecycle,
        hint: 'New, returning, resurrecting and dormant users',
    },
    {
        kind: 'PathsQuery',
        label: 'Paths',
        icon: IconUserPaths,
        hint: 'The routes users take between pages, screens or events',
    },
]
const MATHS: [string, string][] = [
    ['total', 'Total count'],
    ['dau', 'Unique users'],
    ['weekly_active', 'Weekly active users'],
    ['monthly_active', 'Monthly active users'],
    ['unique_session', 'Unique sessions'],
    ['sum', 'Sum of'],
    ['avg', 'Average of'],
    ['min', 'Minimum of'],
    ['max', 'Maximum of'],
    ['median', 'Median of'],
    ['p90', '90th percentile of'],
    ['p95', '95th percentile of'],
    ['p99', '99th percentile of'],
]
const PROPERTY_MATHS = new Set(['sum', 'avg', 'min', 'max', 'median', 'p75', 'p90', 'p95', 'p99'])
const SERIES_COLORS = 8
const letter = (i: number): string => String.fromCharCode(65 + (i % 26))
const ALL_EVENTS = '$$all'

export function EventsBuilder({
    projectId,
    state,
    onChange,
}: {
    projectId: string
    state: EventsState
    onChange: (s: EventsState) => void
}): React.JSX.Element {
    const events = useOptions(projectId, 'hogql', EVENT_OPTIONS.events(), EVENT_OPTIONS.events)
    const src = insightSource(state)
    const used = src ? insightEvents(src) : []
    const props = { events: used }
    const actions = useActionOptions()
    const introspect = useIntrospectPicker(projectId)
    useEffect(() => {
        if (src || !events.data) {
            return
        }
        const first = events.data.includes('$pageview') ? '$pageview' : (events.data[0] ?? '$pageview')
        onChange({ insight: { query: newInsight('TrendsQuery', [first]) } })
    }, [!!src, events.data])
    if (!src) {
        return (
            <div className="py-6 text-center text-xs text-muted-foreground">
                {events.isLoading ? 'Finding events…' : 'No events in this project yet'}
            </div>
        )
    }

    const set = (patch: Record<string, unknown>): void => onChange(withSource(state, { ...src, ...patch }))
    const kind = KINDS.find((k) => k.kind === src.kind) ?? KINDS[0]!
    const pickOptions = [...(events.data ?? []), ALL_EVENTS, ...actions.actions.map((a) => a.pick)]
    const pickLabels = Object.fromEntries([[ALL_EVENTS, 'All events'], ...actions.actions.map((a) => [a.pick, a.name])])
    const pickIcons = Object.fromEntries([
        [ALL_EVENTS, <IconStack key="all" />],
        ...actions.actions.map((a) => [a.pick, <IconTarget key={a.pick} />]),
    ])
    const pickDetails = Object.fromEntries(
        actions.actions.filter((a) => a.description).map((a) => [a.pick, `Action · ${a.description}`])
    )
    const pickValues = Object.fromEntries(
        Object.entries(events.details ?? {}).map(([e, n]) => [e, Number.isFinite(Number(n)) ? short(Number(n)) : n])
    )
    const eventPicker = (i: number, label: string): React.JSX.Element => (
        <Picker
            kind="event"
            label={label}
            options={pickOptions}
            labels={pickLabels}
            icons={pickIcons}
            details={pickDetails}
            values={pickValues}
            loading={events.isLoading}
            {...events.search}
            placeholder="Pick an event"
            value={[used[i] ?? ALL_EVENTS]}
            onChange={([e]) => e && onChange(withSource(state, setInsightEvent(src, i, e === ALL_EVENTS ? null : e)))}
            onBrowse={introspect.open(
                { source: 'events', conds: [] },
                {
                    action: 'Use event',
                    describe: (n) => n.entity && `Use ${n.entity} for ${label}`,
                    hint: 'Point at an event, or open one to see what it carries',
                    apply: (n) => onChange(withSource(state, setInsightEvent(src, i, n.entity ?? null))),
                }
            )}
        />
    )

    return (
        <ProjectScope value={projectId}>
            <div className="flex flex-col gap-4" data-attr="dashboard-v2-events-builder">
                <div className="@container flex flex-col gap-1.5">
                    <Select
                        value={src.kind}
                        onValueChange={(k: any) => k !== src.kind && onChange(switchKind(state, k))}
                    >
                        <SelectTrigger
                            className="h-8 w-full text-xs @min-[22rem]:hidden"
                            aria-label="Insight kind"
                            data-attr="dashboard-v2-insight-kind-select"
                        >
                            <SelectValue>
                                {() => (
                                    <span className="flex items-center gap-2">
                                        <kind.icon className="size-4" />
                                        {kind.label}
                                    </span>
                                )}
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            {KINDS.map((k) => (
                                <SelectItem key={k.kind} value={k.kind}>
                                    <span className="flex items-start gap-2 py-0.5">
                                        <k.icon className="mt-0.5 size-4 shrink-0" />
                                        <span className="flex flex-col">
                                            <span>{k.label}</span>
                                            <span className="text-[11px] text-muted-foreground">{k.hint}</span>
                                        </span>
                                    </span>
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                    <div className="hidden grid-cols-6 gap-1.5 @min-[22rem]:grid">
                        {KINDS.map((k) => (
                            <button
                                key={k.kind}
                                type="button"
                                data-attr={`dashboard-v2-insight-${k.label.toLowerCase()}`}
                                title={k.hint}
                                onClick={() => k.kind !== src.kind && onChange(switchKind(state, k.kind))}
                                className={cn(
                                    'flex flex-col items-center gap-1 rounded-lg border px-1 py-2 text-[11px] transition-colors',
                                    k.kind === src.kind
                                        ? 'border-foreground bg-fill-selected font-medium text-foreground'
                                        : 'text-muted-foreground hover:border-foreground hover:text-foreground'
                                )}
                            >
                                <k.icon className="size-4" />
                                {k.label}
                            </button>
                        ))}
                    </div>
                    <p className="text-xs text-muted-foreground">{kind.hint}</p>
                </div>

                {(src.kind === 'TrendsQuery' || src.kind === 'StickinessQuery') && (
                    <Section title="Series">
                        {src.series.map((n: any, i: number) => (
                            <SeriesRow
                                key={i}
                                i={i}
                                node={n}
                                trends={src.kind === 'TrendsQuery'}
                                picker={eventPicker(i, `Series ${letter(i)}`)}
                                {...props}
                                events={[n.event]}
                                onChange={(m) =>
                                    set({ series: src.series.map((x: any, j: number) => (j === i ? m : x)) })
                                }
                                onRemove={
                                    src.series.length > 1
                                        ? () => set({ series: src.series.filter((_: any, j: number) => j !== i) })
                                        : undefined
                                }
                            />
                        ))}
                        <AddButton
                            onClick={() =>
                                set({
                                    series: [
                                        ...src.series,
                                        eventNode(
                                            used.at(-1) ?? '$pageview',
                                            src.kind === 'TrendsQuery' ? 'total' : undefined
                                        ),
                                    ],
                                })
                            }
                        >
                            Add series
                        </AddButton>
                        {src.kind === 'TrendsQuery' && src.series.length > 1 && (
                            <FormulaInput
                                value={src.trendsFilter?.formula ?? ''}
                                onChange={(formula) =>
                                    set({ trendsFilter: { ...src.trendsFilter, formula: formula || undefined } })
                                }
                            />
                        )}
                    </Section>
                )}

                {src.kind === 'FunnelsQuery' && (
                    <Section title="Steps">
                        <ol className="relative flex flex-col gap-2 before:absolute before:top-3 before:bottom-3 before:left-[11px] before:border-l">
                            {src.series.map((n: any, i: number) => (
                                <li key={i} className="relative flex items-start gap-2">
                                    <span className="z-10 mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border bg-background text-[11px] font-semibold">
                                        {i + 1}
                                    </span>
                                    <SeriesRow
                                        i={i}
                                        node={n}
                                        trends={false}
                                        picker={eventPicker(i, `Step ${i + 1}`)}
                                        {...props}
                                        events={[n.event]}
                                        noBadge
                                        onChange={(m) =>
                                            set({ series: src.series.map((x: any, j: number) => (j === i ? m : x)) })
                                        }
                                        onRemove={
                                            src.series.length > 2
                                                ? () =>
                                                      set({ series: src.series.filter((_: any, j: number) => j !== i) })
                                                : undefined
                                        }
                                    />
                                </li>
                            ))}
                        </ol>
                        <AddButton onClick={() => set({ series: [...src.series, eventNode(null)] })}>
                            Add step
                        </AddButton>
                        <FunnelOptions
                            f={src.funnelsFilter ?? {}}
                            onChange={(funnelsFilter) => set({ funnelsFilter })}
                        />
                    </Section>
                )}

                {src.kind === 'RetentionQuery' && (
                    <RetentionSentence
                        f={src.retentionFilter ?? {}}
                        first={eventPicker(0, 'Start event')}
                        back={eventPicker(1, 'Return event')}
                        onChange={(retentionFilter) => set({ retentionFilter })}
                    />
                )}

                {src.kind === 'LifecycleQuery' && <Section title="Event">{eventPicker(0, 'Event')}</Section>}

                {src.kind === 'PathsQuery' && (
                    <PathsOptions src={src} onChange={(pathsFilter) => set({ pathsFilter })} />
                )}

                <Section title="Filters">
                    <PropertyFilters
                        {...props}
                        context="Every series of this query"
                        value={(src.properties ?? []) as PropertyFilter[]}
                        onChange={(properties) => set({ properties: properties.length ? properties : undefined })}
                    />
                    <label className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Switch
                            checked={!!src.filterTestAccounts}
                            onCheckedChange={(c: boolean) => set({ filterTestAccounts: c || undefined })}
                        />{' '}
                        Filter out internal and test users
                    </label>
                </Section>

                {(src.kind === 'TrendsQuery' || src.kind === 'FunnelsQuery') && (
                    <Section title="Breakdown">
                        <BreakdownPicker
                            {...props}
                            context="Every series of this query, split into one per value"
                            value={
                                breakdownOf(src)
                                    ? {
                                          key: breakdownOf(src)!,
                                          kind: src.breakdownFilter?.breakdown_type === 'person' ? 'person' : 'event',
                                      }
                                    : undefined
                            }
                            onChange={(b) =>
                                set({ breakdownFilter: b ? { breakdown: b.key, breakdown_type: b.kind } : undefined })
                            }
                        />
                    </Section>
                )}

                {(src.kind === 'TrendsQuery' || src.kind === 'StickinessQuery' || src.kind === 'LifecycleQuery') && (
                    <Section title="Grouped by">
                        <Segmented
                            className="w-fit"
                            value={src.interval ?? 'day'}
                            options={[
                                ['hour', 'Hour'],
                                ['day', 'Day'],
                                ['week', 'Week'],
                                ['month', 'Month'],
                            ]}
                            onChange={(interval) => set({ interval })}
                        />
                        {src.kind === 'TrendsQuery' && (
                            <label className="flex items-center gap-2 text-xs text-muted-foreground">
                                <Switch
                                    data-attr="dashboard-v2-compare-previous"
                                    checked={!!src.compareFilter?.compare}
                                    onCheckedChange={(c: boolean) =>
                                        set({ compareFilter: c ? { compare: true } : undefined })
                                    }
                                />{' '}
                                Compare to the previous period
                            </label>
                        )}
                    </Section>
                )}
            </div>
            {introspect.dialog}
        </ProjectScope>
    )
}

const Section = ({ title, children }: { title: string; children: ReactNode }): React.JSX.Element => (
    <section className="flex flex-col gap-2">
        <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</h4>
        {children}
    </section>
)
const AddButton = ({ onClick, children }: { onClick: () => void; children: ReactNode }): React.JSX.Element => (
    <Button variant="default" size="xs" className="w-fit text-muted-foreground" onClick={onClick}>
        <IconPlus className="size-3.5" />
        {children}
    </Button>
)

const breakdownOf = (src: any): string | undefined =>
    src.breakdownFilter?.breakdown ?? src.breakdownFilter?.breakdowns?.[0]?.property
function useProps({ events }: { events: (string | null)[] }): ReturnType<typeof useOptions> {
    return useOptions(useProjectId(), 'hogql', EVENT_OPTIONS.properties(events), (q) =>
        EVENT_OPTIONS.properties(events, q)
    )
}

function SeriesRow({
    i,
    node,
    trends,
    picker,
    events,
    noBadge,
    onChange,
    onRemove,
}: {
    i: number
    node: any
    trends: boolean
    picker: ReactNode
    events: (string | null)[]
    noBadge?: boolean
    onChange: (n: any) => void
    onRemove?: () => void
}): React.JSX.Element {
    const [filtering, setFiltering] = useState(false)
    const [renaming, setRenaming] = useState(false)
    const math = node.math ?? 'total'
    const propertyMath = PROPERTY_MATHS.has(math)
    const keys = useProps({ events })
    const filters = node.properties ?? []
    return (
        <div className="group flex min-w-0 flex-1 flex-col gap-1.5 rounded-lg border bg-card p-2 shadow-xs">
            <div className="flex flex-wrap items-center gap-1.5">
                {!noBadge && (
                    <span
                        className="flex size-5 shrink-0 items-center justify-center rounded text-[11px] font-bold text-white"
                        style={{ background: `var(--data-color-${(i % SERIES_COLORS) + 1})` }}
                    >
                        {letter(i)}
                    </span>
                )}
                {picker}
                {trends && (
                    <Select
                        value={math}
                        onValueChange={(v: any) =>
                            onChange({
                                ...node,
                                math: v,
                                ...(PROPERTY_MATHS.has(v) ? {} : { math_property: undefined }),
                            })
                        }
                    >
                        <SelectTrigger className="h-7 w-auto min-w-28 text-xs">
                            <SelectValue>{(v: any) => MATHS.find(([m]) => m === v)?.[1] ?? v}</SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            {MATHS.map(([v, l]) => (
                                <SelectItem key={v} value={v}>
                                    {l}
                                    {PROPERTY_MATHS.has(v) ? ' a property' : ''}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                )}
                {trends && propertyMath && (
                    <Picker
                        kind="event-property"
                        label="Property"
                        {...keys.search}
                        options={keys.data ?? []}
                        loading={keys.isLoading}
                        placeholder="Pick a property"
                        value={node.math_property ? [node.math_property] : []}
                        onChange={([p]) => onChange({ ...node, math_property: p })}
                    />
                )}
                <div className="ml-auto flex items-center gap-0.5">
                    {!node.custom_name && !renaming && (
                        <Button
                            variant="default"
                            size="icon-xs"
                            title="Rename"
                            aria-label="Rename"
                            className="text-muted-foreground opacity-60 group-hover:opacity-100"
                            onClick={() => setRenaming(true)}
                        >
                            <IconPencil className="size-3" />
                        </Button>
                    )}
                    {!filters.length && !filtering && (
                        <Button
                            variant="default"
                            size="xs"
                            className="text-muted-foreground opacity-60 group-hover:opacity-100"
                            onClick={() => setFiltering(true)}
                        >
                            <IconPlus className="size-3" /> Filter
                        </Button>
                    )}
                    {onRemove && (
                        <Button variant="default" size="icon-xs" title="Remove" aria-label="Remove" onClick={onRemove}>
                            <IconX className="size-3.5" />
                        </Button>
                    )}
                </div>
            </div>
            {(node.custom_name || renaming) && (
                <div className="flex items-center gap-1.5 pl-1">
                    <span className="text-[11px] text-muted-foreground">named</span>
                    <Input
                        autoFocus={renaming}
                        className="h-7 flex-1 text-xs"
                        aria-label="Series name"
                        placeholder={node.name ?? node.event ?? 'All events'}
                        defaultValue={node.custom_name ?? ''}
                        onBlur={(e) => {
                            setRenaming(false)
                            const v = e.target.value.trim()
                            if (v !== (node.custom_name ?? '')) {
                                onChange({ ...node, custom_name: v || undefined })
                            }
                        }}
                        onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
                    />
                </div>
            )}
            {(filters.length > 0 || filtering) && (
                <div className="flex flex-wrap items-center gap-1.5 pl-1">
                    <span className="text-[11px] text-muted-foreground">where</span>
                    <PropertyFilters
                        events={events}
                        context={`${noBadge ? `Step ${i + 1}` : `Series ${letter(i)}`} · ${node.custom_name || (node.kind === 'ActionsNode' ? node.name : (node.event ?? 'All events'))}`}
                        value={filters}
                        autoAdd={filtering && !filters.length}
                        onDismiss={() => setFiltering(false)}
                        onChange={(p) => {
                            setFiltering(false)
                            onChange({ ...node, properties: p.length ? p : undefined })
                        }}
                    />
                </div>
            )}
        </div>
    )
}

function FormulaInput({ value, onChange }: { value: string; onChange: (v: string) => void }): React.JSX.Element {
    const [text, setText] = useState(value)
    useEffect(() => setText(value), [value])
    useEffect(() => {
        if (text === value) {
            return
        }
        const t = setTimeout(() => onChange(text.trim()), 500)
        return () => clearTimeout(t)
    }, [text])
    return (
        <FieldRow side label="Formula">
            <Input
                className="h-7 font-mono text-xs"
                placeholder="e.g. B / A * 100 (empty: each series on its own)"
                value={text}
                onChange={(e) => setText(e.target.value)}
            />
        </FieldRow>
    )
}

function FunnelOptions({ f, onChange }: { f: any; onChange: (f: any) => void }): React.JSX.Element {
    const set = (p: Record<string, unknown>): void => onChange({ ...f, ...p })
    return (
        <div className="mt-1 flex flex-col gap-2">
            <FieldRow side label="Show">
                <Segmented
                    value={f.funnelVizType ?? 'steps'}
                    options={[
                        ['steps', 'Conversion'],
                        ['trends', 'Over time'],
                        ['time_to_convert', 'Time to convert'],
                    ]}
                    onChange={(funnelVizType) => set({ funnelVizType })}
                />
            </FieldRow>
            <FieldRow side label="Step order">
                <Segmented
                    value={f.funnelOrderType ?? 'ordered'}
                    options={[
                        ['ordered', 'Sequential'],
                        ['strict', 'Strict'],
                        ['unordered', 'Any order'],
                    ]}
                    onChange={(funnelOrderType) => set({ funnelOrderType })}
                />
            </FieldRow>
            <FieldRow side label="Within">
                <Input
                    type="number"
                    min={1}
                    className="h-7 w-16 text-xs"
                    value={f.funnelWindowInterval ?? 14}
                    onChange={(e) => set({ funnelWindowInterval: Math.max(1, Number(e.target.value) || 1) })}
                />
                <OptionSelect
                    className="h-7 w-24 text-xs"
                    options={['minute', 'hour', 'day', 'week', 'month'].map((u) => [u, `${u}s`] as const)}
                    value={f.funnelWindowIntervalUnit ?? 'day'}
                    onChange={(funnelWindowIntervalUnit) => set({ funnelWindowIntervalUnit })}
                />
                <span className="text-xs text-muted-foreground">of the first step</span>
            </FieldRow>
        </div>
    )
}

function PathsOptions({ src, onChange }: { src: any; onChange: (f: any) => void }): React.JSX.Element {
    const projectId = useProjectId()
    const f = src.pathsFilter ?? {}
    const set = (p: Record<string, unknown>): void =>
        onChange(Object.fromEntries(Object.entries({ ...f, ...p }).filter(([, v]) => v !== undefined)))
    const opts = pathPointOptions(src)
    const points = useOptions(projectId, 'hogql', opts.query, opts.search)
    const type = (f.includeEventTypes ?? ['$pageview'])[0]
    const what = type === '$pageview' ? 'page' : type === '$screen' ? 'screen' : 'event'
    const point = (key: 'startPoint' | 'endPoint', label: string): React.JSX.Element => (
        <Picker
            kind={`path-${type}`}
            label={label}
            clearable
            {...points.search}
            options={points.data ?? []}
            loading={points.isLoading}
            placeholder={`Any ${what}`}
            value={f[key] ? [f[key]] : []}
            onChange={([v]) => set({ [key]: v || undefined })}
        />
    )
    return (
        <Section title="Paths">
            <FieldRow side label="Steps are">
                <Segmented
                    value={type}
                    options={PATH_TYPES}
                    onChange={(v) =>
                        set({
                            includeEventTypes: [v],
                            startPoint: undefined,
                            endPoint: undefined,
                            excludeEvents: undefined,
                        })
                    }
                />
            </FieldRow>
            <FieldRow side label="Starting at">
                {point('startPoint', 'Start')}
            </FieldRow>
            <FieldRow side label="Ending at">
                {point('endPoint', 'End')}
            </FieldRow>
            <FieldRow side label="Steps">
                <Input
                    type="number"
                    min={2}
                    max={20}
                    className="h-7 w-16 text-xs"
                    aria-label="Steps"
                    value={f.stepLimit ?? 5}
                    onChange={(e) => set({ stepLimit: Math.min(20, Math.max(2, Number(e.target.value) || 5)) })}
                />
            </FieldRow>
            <FieldRow side label="Leave out">
                <Picker
                    kind={`path-${type}`}
                    label="Leave out"
                    multi
                    {...points.search}
                    options={points.data ?? []}
                    loading={points.isLoading}
                    placeholder={`No ${what}s left out`}
                    value={f.excludeEvents ?? []}
                    onChange={(v) => set({ excludeEvents: v.length ? v : undefined })}
                />
            </FieldRow>
        </Section>
    )
}

function RetentionSentence({
    f,
    first,
    back,
    onChange,
}: {
    f: any
    first: ReactNode
    back: ReactNode
    onChange: (f: any) => void
}): React.JSX.Element {
    const set = (p: Record<string, unknown>): void => onChange({ ...f, ...p })
    return (
        <Section title="Who comes back">
            <div className="flex flex-col gap-2 rounded-lg border bg-card p-3 text-xs leading-7 shadow-xs">
                <div className="flex flex-wrap items-center gap-1.5">
                    Users who did {first}
                    <OptionSelect
                        className="h-7 w-auto text-xs"
                        options={[
                            ['retention_first_time', 'for the first time'],
                            ['retention_recurring', 'at any time'],
                        ]}
                        value={f.retentionType ?? 'retention_first_time'}
                        onChange={(retentionType) => set({ retentionType })}
                    />
                </div>
                <div className="flex flex-wrap items-center gap-1.5">and came back to do {back}</div>
                <div className="flex flex-wrap items-center gap-1.5">
                    over the next
                    <Input
                        type="number"
                        min={1}
                        max={30}
                        className="h-7 w-14 text-xs"
                        value={f.totalIntervals ?? 8}
                        onChange={(e) =>
                            set({ totalIntervals: Math.min(30, Math.max(1, Number(e.target.value) || 1)) })
                        }
                    />
                    <Segmented
                        options={[
                            ['Day', 'days'],
                            ['Week', 'weeks'],
                            ['Month', 'months'],
                        ]}
                        value={f.period ?? 'Week'}
                        onChange={(period) => set({ period })}
                    />
                </div>
                <label className="flex items-center gap-2 text-muted-foreground">
                    <Switch
                        data-attr="dashboard-v2-retention-cumulative"
                        checked={!!f.cumulative}
                        onCheckedChange={(c: boolean) => set({ cumulative: c || undefined })}
                    />{' '}
                    Cumulative: back in that period or any later one
                </label>
            </div>
        </Section>
    )
}
