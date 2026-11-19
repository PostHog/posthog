import { Fragment, useEffect, useMemo, useRef, useState } from 'react'

import {
    IconBrackets,
    IconColumns,
    IconCopy,
    IconLetter,
    IconMinus,
    IconPlus,
    IconTextWidth,
    IconX,
} from '@posthog/icons'
import { Badge, Button } from '@posthog/quill'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { editLogs, logsBuilderOf, noId, withFilter, type Filter, type LogsMode, type LogsState } from '../explore/build'
import type { Panel } from '../spec'
import { EmptyData } from './EmptyData'
import { dtf, relativeTime, short } from './format'
import type { DataFrame, Field } from './frame'
import { timeseries, type LogsOptions as O } from './options'
import type { VizProps } from './registry'
import { TimeseriesViz } from './TimeseriesViz'

type Size = 'small' | 'medium' | 'large'
const FONT: Record<Size, number> = { small: 11, medium: 13, large: 15 }
const NEXT: Record<Size, Size> = {
    small: 'medium',
    medium: 'large',
    large: 'small',
}

const MESSAGE = ['body', 'line', 'message', 'msg']
const LEVEL = ['level', 'severity_text', 'severity', 'detected_level']
const LEVEL_COLOR: Record<string, string> = {
    error: 'red',
    fatal: 'red',
    critical: 'red',
    warn: 'amber',
    warning: 'amber',
    info: 'blue',
    debug: 'gray',
    trace: 'gray',
}
const LEVEL_BADGE = {
    red: 'destructive',
    amber: 'warning',
    blue: 'info',
    gray: 'default',
} as const
const LEVEL_BAR = {
    red: 'border-l-red-500',
    amber: 'border-l-amber-500',
    blue: 'border-l-blue-500',
    gray: 'border-l-transparent',
} as const
const field = (f: DataFrame, names: string[]): Field | undefined =>
    f.fields.find((x) => names.includes(x.name.toLowerCase()))
const has = (f: DataFrame, ...names: string[]): boolean => names.every((n) => f.fields.some((x) => x.name === n))
function kinds(frames: DataFrame[]): {
    patterns: DataFrame | undefined
    groups: DataFrame | undefined
    volume: DataFrame[]
} {
    const patterns = frames.find((f) => has(f, 'pattern', 'logs'))
    const groups = frames.find((f) => f !== patterns && has(f, 'logs', 'last_seen') && !field(f, MESSAGE))
    const volume = frames.filter(
        (f) =>
            f.fields.some((x) => x.type === 'number') &&
            f.fields.some((x) => x.type === 'time') &&
            !f.fields.some((x) => x.type === 'string')
    )
    return { patterns, groups, volume }
}
type Edit = ((edit: (p: Panel) => Panel) => void) | undefined
const withColumns = (p: Panel, columns: string[]): Panel => ({
    ...p,
    viz: {
        ...p.viz,
        options: {
            ...p.viz.options,
            columns: columns.length ? columns : undefined,
        },
    },
})
const nf = new Intl.NumberFormat()
const CLIP = 2000

type Row = {
    t: number
    level: string
    service?: string
    message: string
    attrs: unknown
    resource: unknown
    columns: boolean
    traceId?: string
    spanId?: string
}
type OnFilter = ((f: Filter) => void) | undefined

const HISTOGRAM = timeseries.parse({
    stack: true,
    area: true,
    legend: 'none',
    points: false,
    curve: 'linear',
})

export function LogsViz({
    frames,
    panel,
    options,
    height,
    width,
    onEditPanel,
    onTimeRange,
}: VizProps<O>): React.JSX.Element {
    const [openKey, setOpenKey] = useState<string>()
    const [wrap, setWrap] = useState(options.wrap)
    useEffect(() => setWrap(options.wrap), [options.wrap])
    const [size, setSize] = useState<Size>(options.fontSize)
    useEffect(() => setSize(options.fontSize), [options.fontSize])
    const [pretty, setPretty] = useState(options.prettify)
    useEffect(() => setPretty(options.prettify), [options.prettify])
    const list = useRef<HTMLDivElement>(null)
    const builder = logsBuilderOf(panel)?.state
    const search = builder?.search?.trim()
    const { patterns, groups, volume } = useMemo(() => kinds(frames), [frames])
    const columns = options.columns ?? []
    const edit: Edit = onEditPanel
    const editState = builder && edit ? (fn: (s: LogsState) => LogsState) => edit((p) => editLogs(p, fn)) : undefined
    const onFilter: OnFilter = editState && ((f) => editState((s) => withFilter(s, f)))
    const toggleColumn =
        edit &&
        ((k: string) =>
            edit((p) => {
                const cur = ((p.viz.options as O | undefined)?.columns ?? []) as string[]
                return withColumns(p, cur.includes(k) ? cur.filter((c) => c !== k) : [...cur, k])
            }))
    const { rows, limited } = useMemo(() => {
        const out: Row[] = []
        let limited = false
        for (const f of frames) {
            const msg = field(f, MESSAGE)
            if (!msg) {
                continue
            }
            limited ||= msg.values.length >= 100 && msg.values.length % 100 === 0
            const time = f.fields.find((x) => x.type === 'time')
            const level = field(f, LEVEL),
                service = field(f, ['service', 'service_name']),
                attrs = field(f, ['attributes', 'labels']),
                resource = field(f, ['resource_attributes']),
                trace = field(f, ['trace_id', 'traceid']),
                span = field(f, ['span_id', 'spanid'])
            msg.values.forEach((m, i) => {
                const kv = level && service ? {} : Object.fromEntries(attrEntries(attrs?.values[i]))
                const lvl = level?.values[i] ?? LEVEL.map((k) => kv[k]).find(Boolean)
                const svc = service ? service.values[i] : kv.service_name
                out.push({
                    t: Number(time?.values[i] ?? 0),
                    level: String(lvl ?? ''),
                    service: svc != null ? String(svc) : undefined,
                    message: String(m ?? ''),
                    attrs: attrs?.values[i],
                    resource: resource?.values[i],
                    columns: !!(level && service),
                    ...(trace && !noId(trace.values[i])
                        ? { traceId: String(trace.values[i]), spanId: String(span?.values[i] ?? '') }
                        : {}),
                })
            })
        }
        const asc = builder?.order === 'asc'
        out.sort((a, b) => (asc ? a.t - b.t : b.t - a.t))
        return {
            rows: out.slice(0, 1000),
            limited: limited || out.length > 1000,
        }
    }, [frames, builder?.order])
    const open = openKey === undefined ? undefined : rows.findIndex((r) => rowKey(r) === openKey)
    const setOpen = (i: number | undefined): void => setOpenKey(i === undefined ? undefined : rowKey(rows[i]!))
    const mode: LogsMode = builder?.mode ?? (patterns ? 'patterns' : groups && !rows.length ? 'group' : 'lines')
    if (!rows.length && !volume.length && !patterns && !groups) {
        return <EmptyData message="No log lines" />
    }
    const histPanel = {
        ...panel,
        fieldConfig: {
            ...panel.fieldConfig,
            overrides: Object.fromEntries(Object.entries(LEVEL_COLOR).map(([l, c]) => [l, { color: c }])),
        },
    }
    const showHist = options.histogram && volume.length > 0
    const histH = Math.min(120, Math.max(70, Math.round(height * 0.22)))
    const go = (i: number): void => {
        const n = Math.max(0, Math.min(rows.length - 1, i))
        setOpen(n)
        requestAnimationFrame(() =>
            list.current?.querySelector(`[data-row="${n}"]`)?.scrollIntoView({ block: 'nearest' })
        )
    }
    const onKey = (e: React.KeyboardEvent): void => {
        const on = open !== undefined && open >= 0
        const step =
            e.key === 'j' || (e.key === 'ArrowDown' && on) ? 1 : e.key === 'k' || (e.key === 'ArrowUp' && on) ? -1 : 0
        if (step) {
            e.preventDefault()
            go(on ? open + step : 0)
        } else if (e.key === 'Escape' && on) {
            e.stopPropagation()
            setOpen(undefined)
        }
    }

    return (
        <div className="flex h-full min-h-0 flex-col gap-1">
            {showHist && (
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
            <div className="flex shrink-0 flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                {mode === 'lines' && rows.length > 0 && (
                    <>
                        <span
                            title={
                                limited
                                    ? 'The query returned as many lines as its limit: narrow the filters or the time range to see older ones'
                                    : undefined
                            }
                        >
                            {rows.length} lines{limited && ' · newest only'}
                        </span>
                        <span className="hidden lg:inline">· click a line for details, j/k to step</span>
                    </>
                )}
                {mode === 'lines' &&
                    columns.map((k) => (
                        <span key={k} className="flex items-center gap-0.5 rounded bg-muted px-1 font-mono">
                            {k}
                            {toggleColumn && (
                                <button title="Remove this column" onClick={() => toggleColumn(k)}>
                                    <IconX className="size-2.5" />
                                </button>
                            )}
                        </span>
                    ))}
                {mode === 'lines' && (
                    <span className="ml-auto flex items-center gap-2">
                        <button
                            className="flex items-center gap-1 rounded px-1 capitalize hover:text-foreground"
                            title="Text size (the panel's default is in its options)"
                            onClick={() => setSize(NEXT[size])}
                        >
                            <IconLetter className="size-3" /> {size}
                        </button>
                        <button
                            className={`flex items-center gap-1 rounded px-1 hover:text-foreground ${pretty ? 'text-foreground' : ''}`}
                            aria-pressed={pretty}
                            title="Pretty-print JSON lines"
                            onClick={() => setPretty(!pretty)}
                        >
                            <IconBrackets className="size-3" /> JSON
                        </button>
                        <button
                            className={`flex items-center gap-1 rounded px-1 hover:text-foreground ${wrap ? 'text-foreground' : ''}`}
                            aria-pressed={wrap}
                            title="Wrap long lines"
                            onClick={() => setWrap(!wrap)}
                        >
                            <IconTextWidth className="size-3" /> Wrap
                        </button>
                    </span>
                )}
            </div>
            <div className="flex min-h-0 flex-1 gap-1.5">
                {mode === 'patterns' && patterns ? (
                    <PatternsTable frame={patterns} onState={editState} />
                ) : mode === 'group' && groups ? (
                    <GroupTable frame={groups} onState={editState} />
                ) : rows.length > 0 ? (
                    <div
                        ref={list}
                        tabIndex={0}
                        onKeyDown={onKey}
                        style={{ fontSize: FONT[size] }}
                        className="min-h-0 min-w-0 flex-1 overflow-auto rounded border font-mono outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        data-attr="dashboard-v2-log-lines"
                    >
                        <div className={wrap ? '' : 'w-max min-w-full'}>
                            {rows.map((r, i) => {
                                const color = (LEVEL_COLOR[r.level.toLowerCase()] ?? 'gray') as keyof typeof LEVEL_BAR
                                const msg = pretty ? prettyJson(r.message) : r.message
                                const text = !wrap && msg.length > CLIP ? msg.slice(0, CLIP) + '…' : msg
                                return (
                                    <div
                                        key={i}
                                        data-row={i}
                                        className={`border-b last:border-b-0 ${open === i ? 'bg-muted' : 'bg-card hover:bg-muted'}`}
                                    >
                                        <button
                                            className="flex w-full items-start bg-inherit pr-2 text-left"
                                            onClick={() =>
                                                !getSelection()?.toString() && setOpen(open === i ? undefined : i)
                                            }
                                        >
                                            <span
                                                className={`sticky left-0 z-[1] flex shrink-0 items-start gap-2 self-stretch border-l-2 bg-inherit py-0.5 pl-1.5 pr-2 ${LEVEL_BAR[color]}`}
                                            >
                                                <span className="text-muted-foreground tabular-nums">
                                                    {fmtTime(r.t)}
                                                </span>
                                                {r.level && (
                                                    <Badge
                                                        variant={LEVEL_BADGE[color]}
                                                        className="px-1 text-[0.9em] uppercase"
                                                    >
                                                        {r.level.replace(/^warning$/i, 'warn').slice(0, 5)}
                                                    </Badge>
                                                )}
                                                {r.service && (
                                                    <span className="max-w-[20ch] truncate text-muted-foreground">
                                                        {r.service}
                                                    </span>
                                                )}
                                            </span>
                                            {columns.map((k) => {
                                                const v = fieldsOf(r).all.get(k) ?? ''
                                                return (
                                                    <span
                                                        key={k}
                                                        className="w-[18ch] shrink-0 truncate py-0.5 pr-2 text-muted-foreground"
                                                        title={`${k}: ${v}`}
                                                    >
                                                        {v}
                                                    </span>
                                                )
                                            })}
                                            <span
                                                className={`py-0.5 ${wrap ? 'min-w-0 flex-1 whitespace-pre-wrap break-all' : pretty ? 'whitespace-pre' : 'whitespace-nowrap'}`}
                                            >
                                                {marked(text, search)}
                                            </span>
                                        </button>
                                        {open === i && (
                                            <LineDetail
                                                row={r}
                                                rows={rows}
                                                search={search}
                                                onFilter={onFilter}
                                                columns={columns}
                                                onColumn={toggleColumn}
                                                width={wrap ? undefined : width - 2}
                                            />
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                ) : (
                    <EmptyData message="No log lines" />
                )}
            </div>
        </div>
    )
}

function LineDetail({
    row,
    rows,
    search,
    onFilter,
    columns,
    onColumn,
    width,
}: {
    row: Row
    rows: Row[]
    search?: string
    onFilter: OnFilter
    columns: string[]
    onColumn?: (k: string) => void
    width?: number
}): React.JSX.Element {
    const [top, setTop] = useState<string>()
    const { attributes, resource } = fieldsOf(row)
    const section = (title: string, entries: [string, string][], onFilter: OnFilter): false | React.JSX.Element =>
        entries.length > 0 && (
            <div>
                <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {title}
                </div>
                <table className="w-full">
                    <tbody>
                        {entries.map(([k, v]) => (
                            <Fragment key={k}>
                                <tr className="group/attr align-top hover:bg-background">
                                    <td className="w-1/3 py-0.5 pr-2">
                                        <button
                                            className="break-all text-left text-muted-foreground hover:text-foreground hover:underline"
                                            title="Top values in the loaded lines"
                                            onClick={() => setTop(top === k ? undefined : k)}
                                        >
                                            {k}
                                        </button>
                                    </td>
                                    <td className="break-all py-0.5">
                                        <Value v={v} />
                                    </td>
                                    <td className="w-0 whitespace-nowrap">
                                        <span className="flex items-center">
                                            <Actions k={k} v={v} onFilter={onFilter} />
                                            {onColumn && (
                                                <Button
                                                    variant="default"
                                                    size="icon-xs"
                                                    className={
                                                        columns.includes(k)
                                                            ? 'text-primary'
                                                            : 'opacity-0 group-hover/attr:opacity-100'
                                                    }
                                                    title={
                                                        columns.includes(k)
                                                            ? `Remove the ${k} column`
                                                            : `Show ${k} as a column beside each line`
                                                    }
                                                    onClick={() => onColumn(k)}
                                                >
                                                    <IconColumns className="size-3" />
                                                </Button>
                                            )}
                                        </span>
                                    </td>
                                </tr>
                                {top === k && (
                                    <tr>
                                        <td colSpan={3}>
                                            <TopValues k={k} rows={rows} onFilter={onFilter} />
                                        </td>
                                    </tr>
                                )}
                            </Fragment>
                        ))}
                    </tbody>
                </table>
            </div>
        )
    return (
        <div
            className="sticky left-0 flex cursor-auto flex-col gap-2 px-2 pb-2 pl-6"
            style={width ? { width } : undefined}
        >
            <div className="group/attr relative">
                <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all rounded bg-background p-2">
                    {marked(prettyJson(row.message), search)}
                </pre>
                <div className="absolute right-1 top-1">
                    <Actions v={row.message} />
                </div>
            </div>
            {section('Attributes', attributes, onFilter)}
            {section('Resource', resource, onFilter && ((f) => onFilter({ ...f, resource: true })))}
        </div>
    )
}

function TopValues({ k, rows, onFilter }: { k: string; rows: Row[]; onFilter: OnFilter }): React.JSX.Element {
    const counts = new Map<string, number>()
    let has = 0
    for (const r of rows) {
        const v = fieldsOf(r).all.get(k)
        if (v === undefined) {
            continue
        }
        has++
        counts.set(v, (counts.get(v) ?? 0) + 1)
    }
    const top = [...counts].sort((a, b) => b[1] - a[1]).slice(0, 10)
    return (
        <div className="my-1 flex flex-col gap-0.5 rounded border bg-background p-1.5">
            <div className="text-muted-foreground">
                {has} of {rows.length} loaded lines have {k}
                {counts.size > 10 ? ` · ${counts.size} values, top 10` : ''}
            </div>
            {top.map(([v, n]) => (
                <div key={v} className="group/attr flex items-center gap-2 hover:bg-muted">
                    <div className="relative min-w-0 flex-1">
                        <div
                            className="absolute inset-y-0 left-0 rounded-sm bg-primary/15"
                            style={{ width: `${(n / has) * 100}%` }}
                        />
                        <div className="relative truncate px-1" title={v}>
                            {v || '(empty)'}
                        </div>
                    </div>
                    <span className="w-16 shrink-0 text-right tabular-nums text-muted-foreground">
                        {n} · {Math.round((n / has) * 100)}%
                    </span>
                    <Actions k={k} v={v} onFilter={onFilter} />
                </div>
            ))}
        </div>
    )
}

function Actions({ k, v, onFilter }: { k?: string; v: string; onFilter?: OnFilter }): React.JSX.Element {
    const add = (op: Filter['op']): void => {
        onFilter?.({ key: k!, op, value: v })
        lemonToast.success(`Panel filter added: ${k} ${op} ${v.length > 60 ? v.slice(0, 60) + '…' : v}`)
    }
    return (
        <span className="flex items-center opacity-0 transition-opacity group-hover/attr:opacity-100">
            {onFilter && k && (
                <Button
                    variant="default"
                    size="icon-xs"
                    title={`Add ${k} = this to the panel's filters`}
                    onClick={() => add('=')}
                >
                    <IconPlus className="size-3" />
                </Button>
            )}
            {onFilter && k && (
                <Button
                    variant="default"
                    size="icon-xs"
                    title={`Add ${k} != this to the panel's filters`}
                    onClick={() => add('!=')}
                >
                    <IconMinus className="size-3" />
                </Button>
            )}
            <Button
                variant="default"
                size="icon-xs"
                title="Copy"
                onClick={() => {
                    void navigator.clipboard.writeText(v)
                    lemonToast.success('Copied')
                }}
            >
                <IconCopy className="size-3" />
            </Button>
        </span>
    )
}

function Value({ v }: { v: string }): React.JSX.Element {
    const p = prettyJson(v)
    return p === v ? <>{v}</> : <pre className="whitespace-pre-wrap break-all">{p}</pre>
}

function prettyJson(s: string): string {
    if (!/^\s*[[{]/.test(s)) {
        return s
    }
    try {
        const v = JSON.parse(s)
        return typeof v === 'object' && v ? JSON.stringify(v, null, 2) : s
    } catch {
        return s
    }
}

function marked(text: string, q?: string): React.ReactNode {
    if (!q) {
        return text
    }
    const parts = text.split(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'ig'))
    return parts.length === 1
        ? text
        : parts.map((p, i) =>
              i % 2 ? (
                  <mark key={i} className="rounded-sm bg-yellow-200 text-inherit dark:bg-yellow-500/40">
                      {p}
                  </mark>
              ) : (
                  p
              )
          )
}

const fieldsCache = new WeakMap<
    Row,
    {
        attributes: [string, string][]
        resource: [string, string][]
        all: Map<string, string>
    }
>()
function fieldsOf(r: Row): { attributes: [string, string][]; resource: [string, string][]; all: Map<string, string> } {
    let f = fieldsCache.get(r)
    if (!f) {
        const attributes = attrEntries(r.attrs)
        if (r.columns) {
            if (r.service !== undefined) {
                attributes.unshift(['service_name', r.service])
            }
            if (r.level) {
                attributes.unshift(['severity_text', r.level])
            }
        }
        const resource = attrEntries(r.resource)
        f = {
            attributes,
            resource,
            all: new Map([...resource, ...attributes]),
        }
        fieldsCache.set(r, f)
    }
    return f
}

function attrEntries(a: unknown): [string, string][] {
    if (a && typeof a === 'object') {
        return Object.entries(a as Record<string, unknown>)
            .map(([k, v]) => [k, typeof v === 'string' ? v : JSON.stringify(v)] as [string, string])
            .sort(([x], [y]) => x.localeCompare(y))
    }
    if (typeof a === 'string' && a) {
        return a
            .split(' ')
            .map((kv) => {
                const i = kv.indexOf('=')
                return [kv.slice(0, i), kv.slice(i + 1)] as [string, string]
            })
            .filter(([k]) => k)
    }
    return []
}

const rowKey = (r: Row): string => `${r.t}|${r.service}|${r.message.slice(0, 200)}`

function fmtTime(ms: number): string {
    if (!ms) {
        return ''
    }
    const d = new Date(ms)
    const time =
        dtf('hms24', undefined, {
            hour: 'numeric',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
        }).format(d) +
        '.' +
        String(d.getMilliseconds()).padStart(3, '0')
    return d.toDateString() === new Date().toDateString()
        ? time
        : `${dtf('md', undefined, { month: 'short', day: 'numeric' }).format(d)} ${time}`
}

const FACET_LABEL: Record<string, string> = {
    severity_text: 'Level',
    service_name: 'Service',
}

const col = (f: DataFrame, n: string): unknown[] => f.fields.find((x) => x.name === n)?.values ?? []
const ago = (v: unknown): string => (v == null || v === '' ? '' : relativeTime(new Date(Number(v)).toISOString()))
const TH = 'sticky top-0 z-[1] whitespace-nowrap bg-card px-2 py-1 text-left font-medium text-muted-foreground'

function PatternsTable({
    frame,
    onState,
}: {
    frame: DataFrame
    onState?: (fn: (s: LogsState) => LogsState) => void
}): React.JSX.Element {
    const [pattern, logs, errors, services, last] = ['pattern', 'logs', 'errors', 'services', 'last_seen'].map((n) =>
        col(frame, n)
    ) as unknown[][]
    const total = logs!.reduce<number>((a, n) => a + Number(n ?? 0), 0) || 1
    const show = (p: string, op: '=' | '!='): void | undefined =>
        onState?.((s) => ({
            ...withFilter(s, { key: 'pattern', op, value: p }),
            mode: op === '=' ? undefined : s.mode,
        }))
    return (
        <div
            className="min-h-0 min-w-0 flex-1 overflow-auto rounded border text-xs"
            data-attr="dashboard-v2-log-patterns"
        >
            <table className="w-full">
                <thead>
                    <tr>
                        <th className={`${TH} w-full`}>Pattern</th>
                        <th className={`${TH} text-right`}>Lines</th>
                        <th className={`${TH} text-right`}>Share</th>
                        <th className={`${TH} text-right`}>Errors</th>
                        <th className={TH}>Services</th>
                        <th className={TH}>Last seen</th>
                    </tr>
                </thead>
                <tbody>
                    {pattern!.map((p, i) => {
                        const n = Number(logs![i] ?? 0)
                        const e = Number(errors![i] ?? 0)
                        return (
                            <tr
                                key={i}
                                className={`group/attr border-t align-top hover:bg-muted ${onState ? 'cursor-pointer' : ''}`}
                                title={onState ? 'Show the lines of this pattern' : undefined}
                                onClick={() => !getSelection()?.toString() && show(String(p), '=')}
                            >
                                <td className="w-full px-2 py-1 font-mono">
                                    <div className="line-clamp-2 break-all" title={String(p)}>
                                        {String(p)}
                                    </div>
                                </td>
                                <td className="px-2 py-1 text-right tabular-nums" title={nf.format(n)}>
                                    {short(n)}
                                </td>
                                <td className="relative min-w-20 px-2 py-1 text-right tabular-nums">
                                    <div
                                        className="absolute inset-y-1 left-0 rounded-sm bg-primary/15"
                                        style={{
                                            width: `${(n / total) * 100}%`,
                                        }}
                                    />
                                    <span className="relative">{((n / total) * 100).toFixed(1)}%</span>
                                </td>
                                <td
                                    className={`px-2 py-1 text-right tabular-nums ${e ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}
                                >
                                    {e ? short(e) : '–'}
                                </td>
                                <td
                                    className="max-w-[24ch] truncate px-2 py-1 text-muted-foreground"
                                    title={String(services![i] ?? '')}
                                >
                                    {String(services![i] ?? '')}
                                </td>
                                <td className="whitespace-nowrap px-2 py-1 text-muted-foreground">
                                    <span className="flex items-center gap-1">
                                        {ago(last![i])}
                                        {onState && (
                                            <Button
                                                variant="default"
                                                size="icon-xs"
                                                className="opacity-0 group-hover/attr:opacity-100"
                                                title="Hide this pattern"
                                                onClick={(ev) => {
                                                    ev.stopPropagation()
                                                    show(String(p), '!=')
                                                }}
                                            >
                                                <IconMinus className="size-3" />
                                            </Button>
                                        )}
                                    </span>
                                </td>
                            </tr>
                        )
                    })}
                </tbody>
            </table>
        </div>
    )
}

function GroupTable({
    frame,
    onState,
}: {
    frame: DataFrame
    onState?: (fn: (s: LogsState) => LogsState) => void
}): React.JSX.Element {
    const keys = frame.fields.filter((f) => f.type === 'string').map((f) => f.name)
    const [logs, errors, last] = ['logs', 'errors', 'last_seen'].map((n) => col(frame, n)) as unknown[][]
    const show = (i: number): void | undefined =>
        onState?.((s) => ({
            ...keys.reduce((acc, k) => {
                const v = String(col(frame, k)[i] ?? '')
                return v ? withFilter(acc, { key: k, op: '=', value: v }) : acc
            }, s),
            mode: undefined,
        }))
    return (
        <div
            className="min-h-0 min-w-0 flex-1 overflow-auto rounded border text-xs"
            data-attr="dashboard-v2-log-groups"
        >
            <table className="w-full">
                <thead>
                    <tr>
                        {keys.map((k) => (
                            <th key={k} className={`${TH} font-mono`}>
                                {FACET_LABEL[k] ?? k}
                            </th>
                        ))}
                        <th className={`${TH} text-right`}>Lines</th>
                        <th className={`${TH} text-right`}>Errors</th>
                        <th className={TH}>Last seen</th>
                    </tr>
                </thead>
                <tbody>
                    {logs!.map((n, i) => (
                        <tr
                            key={i}
                            className={`border-t hover:bg-muted ${onState ? 'cursor-pointer' : ''}`}
                            title={onState ? 'Show these lines' : undefined}
                            onClick={() => !getSelection()?.toString() && show(i)}
                        >
                            {keys.map((k) => {
                                const v = String(col(frame, k)[i] ?? '')
                                return (
                                    <td key={k} className="max-w-[40ch] truncate px-2 py-1" title={v}>
                                        {v || <span className="text-muted-foreground">(none)</span>}
                                    </td>
                                )
                            })}
                            <td className="px-2 py-1 text-right tabular-nums" title={nf.format(Number(n))}>
                                {short(Number(n ?? 0))}
                            </td>
                            <td
                                className={`px-2 py-1 text-right tabular-nums ${Number(errors![i]) ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}
                            >
                                {Number(errors![i]) ? short(Number(errors![i])) : '–'}
                            </td>
                            <td className="whitespace-nowrap px-2 py-1 text-muted-foreground">{ago(last![i])}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}
