import { useMemo, useState } from 'react'

import { IconArrowLeft, IconChevronDown, IconChevronRight, IconCopy, IconMinus, IconPlus } from '@posthog/icons'
import { Badge, Button } from '@posthog/quill'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import {
    editTraces,
    hexId,
    noId,
    storedId,
    tracesBuilderOf,
    withSpanFilter,
    type Filter,
    type TracesState,
} from '../explore/build'
import type { Panel } from '../spec'
import { EmptyData } from './EmptyData'
import { short } from './format'
import type { DataFrame, Field } from './frame'
import { timeseries, type TracesOptions as O } from './options'
import type { VizProps } from './registry'
import { TimeseriesViz } from './TimeseriesViz'

export type Span = {
    t: number
    ms: number
    traceId: string
    id: string
    parent: string
    name: string
    service: string
    error: boolean
    attrs: unknown
    resource: unknown
    events: unknown
}

const field = (f: DataFrame, ...names: string[]): Field | undefined =>
    f.fields.find((x) => names.includes(x.name.toLowerCase()))
const atLimit = (n: number): boolean => n >= 100 && n % 100 === 0
const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? '' : 's'}`

export function spansOf(frames: DataFrame[]): { spans: Span[]; cut: boolean } {
    const spans: Span[] = []
    let cut = false
    for (const f of frames) {
        const id = field(f, 'span_id')
        if (!id) {
            continue
        }
        cut ||= atLimit(id.values.length)
        const t = field(f, 'timestamp', 'start', 'time') ?? f.fields.find((x) => x.type === 'time')
        const ms = field(f, 'duration_ms', 'duration')
        const nano = field(f, 'duration_nano')
        const end = field(f, 'end_time')
        const [trace, parent, name, service, status, attrs, resource, events] = [
            ['trace_id'],
            ['parent_span_id', 'parent_id'],
            ['name', 'span_name'],
            ['service', 'service_name'],
            ['status_code', 'status', 'is_error'],
            ['attributes'],
            ['resource_attributes'],
            ['events'],
        ].map((n) => field(f, ...n))
        id.values.forEach((v, i) => {
            const start = Number(t?.values[i] ?? 0)
            const st = status?.values[i]
            const isErr =
                status?.name === 'is_error'
                    ? !!Number(st) || st === true
                    : st === 2 || st === '2' || /^error$/i.test(String(st))
            spans.push({
                t: start,
                ms: ms
                    ? Number(ms.values[i] ?? 0)
                    : nano
                      ? Number(nano.values[i] ?? 0) / 1e6
                      : end
                        ? Number(end.values[i] ?? 0) - start
                        : 0,
                traceId: String(trace?.values[i] ?? ''),
                id: String(v ?? ''),
                parent: String(parent?.values[i] ?? ''),
                name: String(name?.values[i] ?? ''),
                service: String(service?.values[i] ?? ''),
                error: isErr,
                attrs: attrs?.values[i],
                resource: resource?.values[i],
                events: events?.values[i],
            })
        })
    }
    return { spans, cut }
}

export type TreeRow = { span: Span; depth: number; children: number; orphan: boolean }
export function spanTree(spans: Span[]): TreeRow[] {
    const ids = new Set(spans.map((s) => s.id))
    const kids = new Map<string, Span[]>()
    const roots: Span[] = []
    for (const s of [...spans].sort((a, b) => a.t - b.t)) {
        if (noId(s.parent) || !ids.has(s.parent) || s.parent === s.id) {
            roots.push(s)
        } else {
            kids.set(s.parent, [...(kids.get(s.parent) ?? []), s])
        }
    }
    const out: TreeRow[] = []
    const seen = new Set<string>()
    const walk = (s: Span, depth: number, orphan: boolean): void => {
        if (seen.has(s.id)) {
            return
        }
        seen.add(s.id)
        const cs = kids.get(s.id) ?? []
        out.push({ span: s, depth, children: cs.length, orphan })
        cs.forEach((c) => walk(c, depth + 1, false))
    }
    roots.forEach((r) => walk(r, 0, !noId(r.parent)))
    return out
}

const SERVICE_COLORS = ['#3b82f6', '#8b5cf6', '#14b8a6', '#f59e0b', '#ec4899', '#0ea5e9', '#84cc16', '#64748b']
const ERROR = '#ef4444'
const HISTOGRAM = timeseries.parse({ stack: true, style: 'bars', legend: 'none', points: false })
const TH = 'sticky top-0 z-[1] whitespace-nowrap bg-card px-2 py-1 text-left font-medium text-muted-foreground'

export function fmtMs(ms: number): string {
    return ms >= 60_000
        ? `${(ms / 60_000).toFixed(1)}m`
        : ms >= 1000
          ? `${(ms / 1000).toFixed(ms >= 10_000 ? 1 : 2)}s`
          : ms >= 1
            ? `${ms.toFixed(ms >= 100 ? 0 : 1)}ms`
            : `${Math.round(ms * 1000)}µs`
}
const fmtTime = (ms: number): string =>
    new Date(ms).toLocaleTimeString(undefined, { hour12: false }) + '.' + String(ms % 1000).padStart(3, '0')

export function TracesViz({
    frames,
    panel,
    options,
    height,
    onEditPanel,
    onTimeRange,
}: VizProps<O>): React.JSX.Element {
    const builder = tracesBuilderOf(panel)?.state
    const volume = useMemo(
        () =>
            frames.filter(
                (f) =>
                    f.fields.some((x) => x.type === 'number') &&
                    f.fields.some((x) => x.type === 'time') &&
                    !f.fields.some((x) => x.type === 'string')
            ),
        [frames]
    )
    const { spans, cut } = useMemo(() => spansOf(frames), [frames])
    const ops = useMemo(() => frames.find((f) => field(f, 'requests') && field(f, 'p95_ms')), [frames])
    const one =
        !!builder?.traceId || (spans.length > 0 && spans.every((s) => s.traceId === spans[0]!.traceId) && !builder)
    const want = builder?.traceId ? storedId(builder.traceId) : undefined
    const traceSpans = want ? spans.filter((s) => s.traceId === want) : spans
    const traceFrames = frames.some((f) => field(f, 'events'))
    const stale =
        !!builder &&
        frames.length > 0 &&
        (want ? !traceFrames || (spans.length > 0 && !traceSpans.length) : traceFrames)
    const edit =
        onEditPanel && builder
            ? (fn: Parameters<typeof editTraces>[1]) => onEditPanel((p) => editTraces(p, fn))
            : undefined
    const open = (s: Span): void | undefined => edit?.((b) => ({ ...b, traceId: s.traceId }))
    const openOperation = (service: string, name: string): void => {
        const next = (b: TracesState): TracesState => ({
            ...b,
            services: [service],
            names: [name],
            mode: 'spans',
            order: 'duration',
        })
        edit?.(next)
    }
    const back = edit && (() => edit(({ traceId: _t, ...b }) => b))
    if (stale) {
        return (
            <div className="flex h-full flex-col gap-2" data-attr="dashboard-v2-traces-loading">
                {want && back && <BackButton onBack={back} />}
                <EmptyData message={want ? 'Loading the trace…' : 'Loading…'} />
            </div>
        )
    }
    if (one) {
        return <Waterfall spans={traceSpans} cut={cut} onBack={back} />
    }
    if (!spans.length && !volume.length && !ops) {
        return <EmptyData message="No traces" />
    }
    const histH = Math.min(110, Math.max(60, Math.round(height * 0.2)))
    const histPanel: Panel = {
        ...panel,
        fieldConfig: { ...panel.fieldConfig, overrides: { error: { color: ERROR }, ok: { color: SERVICE_COLORS[0] } } },
    }
    const max = Math.max(1, ...spans.map((s) => s.ms))
    const onFilter = edit && ((f: Filter) => edit((b) => withSpanFilter(b, f)))
    return (
        <div className="flex h-full min-h-0 flex-col gap-1">
            {options.histogram && volume.length > 0 && (
                <div className="flex shrink-0 flex-col" style={{ height: histH }}>
                    <TimeseriesViz
                        frames={volume}
                        panel={histPanel}
                        options={HISTOGRAM}
                        height={histH}
                        width={0}
                        onTimeRange={onTimeRange}
                    />
                </div>
            )}
            {ops ? (
                <OperationsTable frame={ops} onOpen={openOperation} />
            ) : (
                <>
                    <div className="shrink-0 text-[10px] text-muted-foreground">
                        <span
                            title={
                                cut
                                    ? 'As many as the query returns at most: narrow the filters or the time range'
                                    : undefined
                            }
                        >
                            {plural(spans.length, builder?.mode === 'spans' ? 'span' : 'trace')}
                            {cut && (builder?.order === 'duration' ? ' · slowest only' : ' · newest only')}
                        </span>
                        <span className="hidden lg:inline"> · click one to see its spans</span>
                    </div>
                    <div
                        className="min-h-0 flex-1 overflow-auto rounded border text-xs"
                        data-attr="dashboard-v2-trace-list"
                    >
                        <table className="w-full">
                            <thead>
                                <tr>
                                    <th className={TH}>Time</th>
                                    <th className={TH}>Service</th>
                                    <th className={`${TH} w-full`}>Name</th>
                                    <th className={`${TH} text-right`}>Duration</th>
                                </tr>
                            </thead>
                            <tbody>
                                {spans.map((s, i) => (
                                    <tr
                                        key={i}
                                        className="group/attr cursor-pointer border-t hover:bg-muted"
                                        onClick={() => !getSelection()?.toString() && open(s)}
                                    >
                                        <td className="whitespace-nowrap px-2 py-1 tabular-nums text-muted-foreground">
                                            {fmtTime(s.t)}
                                        </td>
                                        <td className="max-w-[24ch] truncate px-2 py-1" title={s.service}>
                                            <span className="flex items-center gap-1">
                                                {s.service}
                                                {onFilter && (
                                                    <FilterButtons k="service_name" v={s.service} onFilter={onFilter} />
                                                )}
                                            </span>
                                        </td>
                                        <td className="max-w-0 px-2 py-1 font-mono">
                                            <span className="flex items-center gap-1.5">
                                                {s.error && (
                                                    <Badge variant="destructive" className="px-1 text-[10px]">
                                                        error
                                                    </Badge>
                                                )}
                                                <span className="truncate" title={s.name}>
                                                    {s.name}
                                                </span>
                                                {onFilter && <FilterButtons k="name" v={s.name} onFilter={onFilter} />}
                                            </span>
                                        </td>
                                        <td className="relative min-w-28 px-2 py-1 text-right tabular-nums">
                                            <div
                                                className="absolute inset-y-1 left-0 rounded-sm"
                                                style={{
                                                    width: `${(s.ms / max) * 100}%`,
                                                    background: s.error
                                                        ? `${ERROR}33`
                                                        : 'color-mix(in srgb, var(--primary) 15%, transparent)',
                                                }}
                                            />
                                            <span className="relative">{fmtMs(s.ms)}</span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </>
            )}
        </div>
    )
}

const OP_TH = `${TH} text-right`
function OperationsTable({
    frame,
    onOpen,
}: {
    frame: DataFrame
    onOpen: (service: string, name: string) => void
}): React.JSX.Element {
    const col = (n: string): unknown[] => field(frame, n)?.values ?? []
    const [service, name, requests, errors, p50, p95, p99, total, sessions, people] = [
        'service',
        'name',
        'requests',
        'errors',
        'p50_ms',
        'p95_ms',
        'p99_ms',
        'total_ms',
        'sessions',
        'people',
    ].map(col)
    const impact = !!field(frame, 'sessions')
    const sum = total!.reduce<number>((a, v) => a + Number(v ?? 0), 0) || 1
    const cut = atLimit(service!.length)
    return (
        <>
            <div className="shrink-0 text-[10px] text-muted-foreground">
                {plural(service!.length, 'operation')}
                {cut && ' · the busiest only'}
                <span className="hidden lg:inline"> · click one to see its slowest spans</span>
            </div>
            <div
                className="min-h-0 flex-1 overflow-auto rounded border text-xs"
                data-attr="dashboard-v2-trace-operations"
            >
                <table className="w-full">
                    <thead>
                        <tr>
                            <th className={TH}>Service</th>
                            <th className={`${TH} w-full`}>Operation</th>
                            <th className={OP_TH}>Requests</th>
                            <th className={OP_TH}>Errors</th>
                            <th className={OP_TH}>p50</th>
                            <th className={OP_TH}>p95</th>
                            <th className={OP_TH}>p99</th>
                            <th className={OP_TH} title="Share of all span time in range">
                                Time
                            </th>
                            {impact && <th className={OP_TH}>Sessions</th>}
                            {impact && <th className={OP_TH}>People</th>}
                        </tr>
                    </thead>
                    <tbody>
                        {service!.map((svc, i) => {
                            const n = Number(requests![i] ?? 0)
                            const e = Number(errors![i] ?? 0)
                            const share = Number(total![i] ?? 0) / sum
                            return (
                                <tr
                                    key={i}
                                    className="cursor-pointer border-t hover:bg-muted"
                                    onClick={() => !getSelection()?.toString() && onOpen(String(svc), String(name![i]))}
                                >
                                    <td className="max-w-[24ch] truncate px-2 py-1" title={String(svc)}>
                                        {String(svc)}
                                    </td>
                                    <td className="max-w-0 truncate px-2 py-1 font-mono" title={String(name![i])}>
                                        {String(name![i])}
                                    </td>
                                    <td className="px-2 py-1 text-right tabular-nums">{short(n)}</td>
                                    <td
                                        className={`whitespace-nowrap px-2 py-1 text-right tabular-nums ${e ? 'text-destructive-foreground' : 'text-muted-foreground'}`}
                                        title={`${e} of ${n}`}
                                    >
                                        {e ? `${((e / n) * 100).toFixed(e / n < 0.01 ? 2 : 1)}%` : '–'}
                                    </td>
                                    {[p50, p95, p99].map((p, k) => (
                                        <td key={k} className="whitespace-nowrap px-2 py-1 text-right tabular-nums">
                                            {fmtMs(Number(p![i] ?? 0))}
                                        </td>
                                    ))}
                                    <td className="relative min-w-20 px-2 py-1 text-right tabular-nums">
                                        <div
                                            className="absolute inset-y-1 left-0 rounded-sm bg-primary/15"
                                            style={{ width: `${share * 100}%` }}
                                        />
                                        <span className="relative">{(share * 100).toFixed(1)}%</span>
                                    </td>
                                    {impact && (
                                        <td className="px-2 py-1 text-right tabular-nums">
                                            {short(Number(sessions![i] ?? 0))}
                                        </td>
                                    )}
                                    {impact && (
                                        <td className="px-2 py-1 text-right tabular-nums">
                                            {short(Number(people![i] ?? 0))}
                                        </td>
                                    )}
                                </tr>
                            )
                        })}
                    </tbody>
                </table>
            </div>
        </>
    )
}

function FilterButtons({ k, v, onFilter }: { k: string; v: string; onFilter: (f: Filter) => void }): React.JSX.Element {
    const add = (op: Filter['op']) => (e: React.MouseEvent) => {
        e.stopPropagation()
        onFilter({ key: k, op, value: v })
    }
    return (
        <span className="flex shrink-0 opacity-0 group-hover/attr:opacity-100">
            <Button variant="default" size="icon-xs" title={`Only ${v}`} onClick={add('=')}>
                <IconPlus className="size-3" />
            </Button>
            <Button variant="default" size="icon-xs" title={`Leave out ${v}`} onClick={add('!=')}>
                <IconMinus className="size-3" />
            </Button>
        </span>
    )
}

function Waterfall({ spans, cut, onBack }: { spans: Span[]; cut: boolean; onBack?: () => void }): React.JSX.Element {
    const rows = useMemo(() => spanTree(spans), [spans])
    const [closed, setClosed] = useState<Set<string>>(new Set())
    const [picked, setPicked] = useState<string>()
    if (!spans.length) {
        return (
            <div className="flex h-full flex-col gap-2">
                {onBack && <BackButton onBack={onBack} />}
                <EmptyData message="Trace not found in this time range. Spans are kept 15 days by default: widen the range if it is older." />
            </div>
        )
    }
    const start = Math.min(...spans.map((s) => s.t))
    const end = Math.max(...spans.map((s) => s.t + s.ms))
    const total = Math.max(end - start, 0.001)
    const services = [...new Set(rows.map((r) => r.span.service))]
    const color = (s: Span): string =>
        s.error ? ERROR : SERVICE_COLORS[services.indexOf(s.service) % SERVICE_COLORS.length]
    const root = rows[0]!.span
    const errors = spans.filter((s) => s.error).length
    const traceId = root.traceId
    const visible: TreeRow[] = []
    let hideBelow = Infinity
    for (const r of rows) {
        if (r.depth > hideBelow) {
            continue
        }
        hideBelow = closed.has(r.span.id) ? r.depth : Infinity
        visible.push(r)
    }
    return (
        <div className="flex h-full min-h-0 flex-col gap-1.5 text-xs" data-attr="dashboard-v2-trace-waterfall">
            <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1">
                {onBack && <BackButton onBack={onBack} />}
                <span className="font-medium">{root.name || '(unnamed)'}</span>
                <span className="text-muted-foreground">
                    {fmtMs(total)} · {spans.length} spans{cut && ' (the query’s limit: there may be more)'} ·{' '}
                    {services.length} {services.length === 1 ? 'service' : 'services'}
                    {errors > 0 && <span className="text-destructive-foreground"> · {errors} errors</span>}
                </span>
                <span className="ml-auto flex items-center gap-1">
                    {traceId && (
                        <>
                            <CopyButton label="Copy trace id" v={hexId(traceId)} />
                        </>
                    )}
                </span>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2 text-[10px] text-muted-foreground">
                {services.map((s, i) => (
                    <span key={s} className="flex items-center gap-1">
                        <span
                            className="size-2 rounded-sm"
                            style={{ background: SERVICE_COLORS[i % SERVICE_COLORS.length] }}
                        />
                        {s || '(no service)'}
                    </span>
                ))}
            </div>
            <div className="min-h-0 flex-1 overflow-auto rounded border">
                {visible.map((r) => {
                    const s = r.span
                    const isOpen = picked === s.id
                    return (
                        <div key={s.id} className="border-b last:border-b-0">
                            <div
                                className={`flex cursor-pointer items-center gap-2 px-1 py-0.5 ${isOpen ? 'bg-muted' : 'hover:bg-muted'}`}
                                onClick={() => !getSelection()?.toString() && setPicked(isOpen ? undefined : s.id)}
                            >
                                <div
                                    className="flex w-2/5 min-w-0 shrink-0 items-center gap-1"
                                    style={{ paddingLeft: Math.min(r.depth, 20) * 12 }}
                                >
                                    {r.children > 0 ? (
                                        <button
                                            className="text-muted-foreground hover:text-foreground"
                                            title={closed.has(s.id) ? `Show ${r.children} child spans` : 'Collapse'}
                                            onClick={(e) => {
                                                e.stopPropagation()
                                                const n = new Set(closed)
                                                n.has(s.id) ? n.delete(s.id) : n.add(s.id)
                                                setClosed(n)
                                            }}
                                        >
                                            {closed.has(s.id) ? (
                                                <IconChevronRight className="size-3" />
                                            ) : (
                                                <IconChevronDown className="size-3" />
                                            )}
                                        </button>
                                    ) : (
                                        <span className="w-3 shrink-0" />
                                    )}
                                    <span className="size-2 shrink-0 rounded-sm" style={{ background: color(s) }} />
                                    <span className="truncate font-mono" title={`${s.service} · ${s.name}`}>
                                        {s.name || '(unnamed)'}
                                    </span>
                                    {r.orphan && (
                                        <span
                                            className="shrink-0 text-[10px] text-muted-foreground"
                                            title="Its parent span isn’t in this trace’s results"
                                        >
                                            parent missing
                                        </span>
                                    )}
                                </div>
                                <div className="relative h-4 min-w-0 flex-1">
                                    <div
                                        className="absolute inset-y-0.5 rounded-sm"
                                        style={{
                                            left: `${((s.t - start) / total) * 100}%`,
                                            width: `max(2px, ${(s.ms / total) * 100}%)`,
                                            background: color(s),
                                        }}
                                    />
                                </div>
                                <span className="w-16 shrink-0 text-right tabular-nums text-muted-foreground">
                                    {fmtMs(s.ms)}
                                </span>
                            </div>
                            {isOpen && <SpanDetail span={s} />}
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

function BackButton({ onBack }: { onBack: () => void }): React.JSX.Element {
    return (
        <Button variant="outline" size="xs" onClick={onBack} data-attr="dashboard-v2-trace-back">
            <IconArrowLeft className="size-3" /> All traces
        </Button>
    )
}

function CopyButton({ label, v }: { label: string; v: string }): React.JSX.Element {
    return (
        <Button
            variant="default"
            size="icon-xs"
            title={label}
            onClick={() => {
                void navigator.clipboard.writeText(v)
                lemonToast.success('Copied')
            }}
        >
            <IconCopy className="size-3" />
        </Button>
    )
}

const entries = (a: unknown): [string, string][] =>
    a && typeof a === 'object'
        ? Object.entries(a as Record<string, unknown>)
              .map(([k, v]) => [k, typeof v === 'string' ? v : JSON.stringify(v)] as [string, string])
              .sort(([x], [y]) => x.localeCompare(y))
        : []

function SpanDetail({ span: s }: { span: Span }): React.JSX.Element {
    const events = (Array.isArray(s.events) ? s.events : []).map((e) => {
        try {
            return typeof e === 'string' ? JSON.parse(e) : e
        } catch {
            return { name: String(e) }
        }
    })
    const section = (title: string, list: [string, string][]): false | React.JSX.Element =>
        list.length > 0 && (
            <div>
                <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {title}
                </div>
                <table className="w-full">
                    <tbody>
                        {list.map(([k, v]) => (
                            <tr key={k} className="align-top hover:bg-background">
                                <td className="w-1/3 break-all py-0.5 pr-2 text-muted-foreground">{k}</td>
                                <td className="break-all py-0.5 font-mono">{v}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        )
    return (
        <div className="flex flex-col gap-2 bg-muted px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono">{s.name}</span>
                <span className="text-muted-foreground">
                    {s.service} · {fmtMs(s.ms)} · started {fmtTime(s.t)}
                </span>
                {s.error && <Badge variant="destructive">error</Badge>}
                <span className="ml-auto flex items-center gap-1">
                    <CopyButton label="Copy span id" v={hexId(s.id)} />
                </span>
            </div>
            {section('Attributes', entries(s.attrs))}
            {section(
                'Events',
                events.map((e: any, i: number) => [
                    `${e?.name ?? `event ${i + 1}`}`,
                    JSON.stringify(e?.attributes ?? e ?? {}),
                ])
            )}
            {section('Resource', entries(s.resource))}
        </div>
    )
}
