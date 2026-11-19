import { Fragment, useState } from 'react'

import { IconChevronLeft, IconChevronRight, IconTriangleDownFilled, IconTriangleUpFilled } from '@posthog/icons'
import { Button, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@posthog/quill'

import { Link } from 'lib/lemon-ui/Link'

import { useDisplayChartTheme } from '../editor/display'
import type { DashboardV2FieldOverrideApi } from '../generated/api.schemas'
import { colorToken, fieldOverride, mapValue } from './chartCommon'
import { byValue, colorize, valueColor } from './colors'
import { EmptyData } from './EmptyData'
import { dateTime, formatValue, relativeTime } from './format'
import { toTable } from './frames'
import { reduce } from './frames'
import { dataLink } from './links'
import type { TableOptions as O } from './options'
import type { VizProps } from './registry'

export function TableViz({ frames, panel, options, time, timezone, onDrill }: VizProps<O>): React.JSX.Element {
    const theme = useDisplayChartTheme()
    const [open, setOpen] = useState<Set<string>>(new Set())
    const [sort, setSort] = useState<{ name: string; desc: boolean }>()
    const [page, setPage] = useState(0)
    const merged = (panel.transforms ?? []).some((t) => t.type === 'merge')
    const grafana = (n: string): string[] =>
        n === 'value' ? ['Value'] : merged && frames.some((f) => f.refId === n) ? [`Value #${n}`] : []
    const overrideOf = (n: string): DashboardV2FieldOverrideApi | undefined =>
        [n, ...grafana(n)].map((x) => fieldOverride(panel, x)).find(Boolean)
    const table = toTable(frames, panel.transforms ?? [], (n) => [...grafana(n), overrideOf(n)?.displayName ?? n])
    const names = new Set(table.columns.map((c) => c.name))
    const linkOf = (n: string): string | undefined => (names.has(`${n} (link)`) ? `${n} (link)` : undefined)
    const keep = table.columns
        .map((c, i) => ({ c, i, o: overrideOf(c.name) }))
        .filter((x) => !x.o?.hidden && !(x.c.name.endsWith(' (link)') && names.has(x.c.name.slice(0, -7))))
    const columns = keep.map(({ c, o }) => ({
        ...c,
        label: o?.displayName ?? c.name,
        cell: o?.cell,
        link: o?.link,
        wrap: o?.wrap,
        linkColumn: linkOf(c.name),
    }))
    const rows = table.rows.map((r) => keep.map(({ i }) => r[i]))
    const colMax = columns.map(
        (_, ci) => panel.fieldConfig?.max ?? Math.max(0, ...rows.map((r) => Number(r[ci])).filter(Number.isFinite))
    )
    const colMin = columns.map((_, ci) => Math.min(...rows.map((r) => Number(r[ci])).filter(Number.isFinite)))
    const mode = panel.fieldConfig?.color?.mode
    const numeric = columns.filter((c) => c.type === 'number')
    const colColor = byValue(mode ?? 'thresholds')
        ? undefined
        : new Map(
              colorize(
                  panel,
                  numeric.map((c) => ({ label: c.name, data: [] })),
                  theme.colors
              ).map((s) => [s.label, s.color])
          )
    const cellColor = (v: unknown, ci: number): string | undefined => {
        const col = columns[ci]!
        const own = overrideOf(col.name)?.color
        const n =
            typeof v === 'number' || (typeof v === 'string' && v !== '' && !Number.isNaN(Number(v))) ? Number(v) : null
        const rules = overrideOf(col.name)?.mappings
        const ruled = mapValue(panel, v as any, rules)
        return (
            ruled?.color ??
            (own
                ? colorToken(own)
                : rules?.length
                  ? undefined
                  : colColor
                    ? colColor.get(col.name)
                    : valueColor(panel, n, colMin[ci]!, colMax[ci]!))
        )
    }
    const fmt = (v: unknown, type: string, unit?: string, name?: string): string => {
        const mapped = mapValue(panel, v as any, name ? overrideOf(name)?.mappings : undefined)?.text
        if (mapped !== undefined) {
            return mapped
        }
        const o = name ? overrideOf(name) : undefined
        if (o && type === 'number' && v !== null && v !== undefined) {
            return formatValue(
                Number(v),
                o.unit ?? panel.fieldConfig?.unit ?? unit,
                o.decimals ?? panel.fieldConfig?.decimals
            )
        }
        if (v === null || v === undefined) {
            return '–'
        }
        if (type === 'time' && (o?.unit ?? unit) === 'dateTimeFromNow') {
            return relativeTime(new Date(Number(v)).toISOString())
        }
        if (type === 'time') {
            return unit === 'date' ? new Date(Number(v)).toISOString().slice(0, 10) : dateTime(Number(v), timezone)
        }
        if (type === 'number') {
            return formatValue(Number(v), panel.fieldConfig?.unit ?? unit, panel.fieldConfig?.decimals)
        }
        return String(v)
    }
    const rowFields = (ri: number): { [k: string]: unknown } =>
        Object.fromEntries(table.columns.map((c, i) => [c.name, table.rows[ri]![i]]))
    const cell = (v: unknown, ci: number, ri: number): string | React.JSX.Element => {
        const col = columns[ci]!
        const own = col.linkColumn ? rowFields(ri)[col.linkColumn] : undefined
        const href = col.link
            ? dataLink(col.link, v, rowFields(ri), time)
            : typeof own === 'string' && safeHref(own)
              ? own
              : undefined
        const inner = styled(v, ci)
        if (!href) {
            return inner
        }
        return (
            <Link
                to={href}
                target={/^https?:/i.test(href) ? '_blank' : undefined}
                className="underline decoration-dotted underline-offset-2"
            >
                {inner}
            </Link>
        )
    }
    const styled = (v: unknown, ci: number): string | React.JSX.Element => {
        const col = columns[ci]!,
            text = fmt(v, col.type, col.unit, col.name),
            color = col.cell ? cellColor(v, ci) : undefined
        if (col.cell === 'bar' && col.type === 'number' && v !== null && v !== undefined) {
            const pct = colMax[ci]! > 0 ? Math.max(0, Math.min(1, Number(v) / colMax[ci]!)) : 0
            return (
                <div className="flex items-center gap-2">
                    <div className="relative h-3 min-w-16 flex-1 rounded-sm bg-muted">
                        <div
                            className="absolute inset-y-0 left-0 rounded-sm"
                            style={{ width: `${pct * 100}%`, background: color ?? 'var(--color-chart-1, #1d4aff)' }}
                        />
                    </div>
                    <span>{text}</span>
                </div>
            )
        }
        if (col.cell === 'color-text' && color) {
            return <span style={{ color }}>{text}</span>
        }
        return text
    }
    const footer =
        options.footer && rows.length
            ? columns.map((c, ci) =>
                  c.type === 'number'
                      ? fmt(
                            reduce(
                                rows.map((r) => (r[ci] === null || r[ci] === undefined ? null : Number(r[ci]))),
                                options.footer!
                            ),
                            c.type,
                            c.unit,
                            c.name
                        )
                      : ci === 0
                        ? options.footer
                        : ''
              )
            : undefined
    const detail = (v: unknown, type: string, unit?: string, name?: string): string => {
        if (typeof v === 'string' && /^[[{]/.test(v.trim())) {
            try {
                return JSON.stringify(JSON.parse(v), null, 2)
            } catch {}
        }
        if (type === 'time' && v !== null && v !== undefined) {
            return dateTime(Number(v), timezone)
        }
        return fmt(v, type, unit, name)
    }
    if (!rows.length) {
        return <EmptyData />
    }
    const sortCol = sort ? columns.findIndex((c) => c.name === sort.name) : -1
    const order = sortCol >= 0 ? sortedOrder(rows, sortCol, sort!.desc) : rows.map((_, i) => i)
    const size = options.pageSize
    const pages = Math.max(1, Math.ceil(rows.length / size))
    const at = Math.min(page, pages - 1)
    const shown = order.slice(at * size, (at + 1) * size)
    const sortBy = (name: string, type: string): void => {
        setSort((s) => (s?.name === name ? { name, desc: !s.desc } : { name, desc: type === 'number' }))
        setPage(0)
    }
    return (
        <div className="h-full overflow-auto">
            <Table className="text-xs">
                {options.showHeader && (
                    <TableHeader className="sticky top-0 bg-card">
                        <TableRow>
                            {options.expandable && <TableHead className="w-6" />}
                            {columns.map((c) => (
                                <TableHead
                                    key={c.name}
                                    className={`min-w-16 max-w-48 cursor-pointer whitespace-normal break-words select-none hover:text-foreground ${c.type === 'number' ? 'text-right' : ''}`}
                                    onClick={() => sortBy(c.name, c.type)}
                                    aria-sort={
                                        sort?.name === c.name ? (sort.desc ? 'descending' : 'ascending') : undefined
                                    }
                                >
                                    {c.label}
                                    {sort?.name === c.name &&
                                        (sort.desc ? (
                                            <IconTriangleDownFilled className="ml-0.5 inline size-3" />
                                        ) : (
                                            <IconTriangleUpFilled className="ml-0.5 inline size-3" />
                                        ))}
                                </TableHead>
                            ))}
                        </TableRow>
                    </TableHeader>
                )}
                <TableBody>
                    {shown.map((i) => {
                        const r = rows[i]!
                        const key = JSON.stringify(table.rows[i]).slice(0, 300)
                        const isOpen = open.has(key)
                        const toggle = (): void =>
                            setOpen((o) => {
                                const n = new Set(o)
                                if (n.has(key)) {
                                    n.delete(key)
                                } else {
                                    n.add(key)
                                }
                                return n
                            })
                        return (
                            <Fragment key={key + i}>
                                <TableRow
                                    className={options.expandable ? 'cursor-pointer' : undefined}
                                    onClick={
                                        options.expandable
                                            ? (e) => {
                                                  if (!(e.target as HTMLElement).closest('a')) {
                                                      toggle()
                                                  }
                                              }
                                            : undefined
                                    }
                                >
                                    {options.expandable && (
                                        <TableCell className="w-6 pr-0">
                                            <IconChevronRight
                                                className={`size-3.5 text-muted-foreground transition-transform ${isOpen ? 'rotate-90' : ''}`}
                                            />
                                        </TableCell>
                                    )}
                                    {r.map((v, ci) => {
                                        const col = columns[ci]!
                                        const bg = col.cell === 'color-background' ? cellColor(v, ci) : undefined
                                        const title =
                                            col.type === 'time' && v !== null && v !== undefined
                                                ? dateTime(Number(v), timezone)
                                                : undefined
                                        const drill = onDrill
                                            ? (e: React.MouseEvent) => {
                                                  if (
                                                      (e.target as HTMLElement).closest('a') ||
                                                      !(e.metaKey || e.ctrlKey)
                                                  ) {
                                                      return
                                                  }
                                                  e.stopPropagation()
                                                  onDrill({
                                                      refId: frames[0]?.refId,
                                                      row: rowFields(i),
                                                      value: v,
                                                      series: { name: col.name },
                                                      category: r[0] == null ? undefined : String(r[0]),
                                                  })
                                              }
                                            : undefined
                                        return (
                                            <TableCell
                                                key={ci}
                                                title={title}
                                                onClick={drill}
                                                className={`${col.type === 'number' ? 'text-right tabular-nums' : col.wrap ? 'min-w-56 max-w-md whitespace-normal break-words' : 'font-mono'} `}
                                                style={bg ? { background: bg, color: textOn(bg) } : undefined}
                                            >
                                                {cell(v, ci, i)}
                                            </TableCell>
                                        )
                                    })}
                                </TableRow>
                                {isOpen && (
                                    <TableRow className="bg-muted/30 hover:bg-muted/30">
                                        <TableCell colSpan={columns.length + 1} className="whitespace-normal">
                                            <dl className="grid grid-cols-[minmax(0,12rem)_minmax(0,1fr)] gap-x-4 gap-y-1 py-1">
                                                {table.columns.map((c, ci) => {
                                                    const v = table.rows[i]![ci]
                                                    return (
                                                        <Fragment key={c.name}>
                                                            <dt className="truncate text-muted-foreground">{c.name}</dt>
                                                            <dd className="min-w-0 font-mono break-words whitespace-pre-wrap">
                                                                {detail(v, c.type, c.unit, c.name)}
                                                            </dd>
                                                        </Fragment>
                                                    )
                                                })}
                                            </dl>
                                        </TableCell>
                                    </TableRow>
                                )}
                            </Fragment>
                        )
                    })}
                    {footer && (
                        <TableRow className="sticky bottom-0 bg-card font-medium">
                            {options.expandable && <TableCell />}
                            {footer.map((v, ci) => (
                                <TableCell
                                    key={ci}
                                    className={
                                        columns[ci]!.type === 'number'
                                            ? 'text-right tabular-nums'
                                            : 'text-muted-foreground'
                                    }
                                >
                                    {v}
                                </TableCell>
                            ))}
                        </TableRow>
                    )}
                </TableBody>
            </Table>
            {pages > 1 && (
                <div className="sticky bottom-0 flex items-center justify-end gap-1 border-t bg-card px-2 py-1 text-xs text-muted-foreground">
                    {at * size + 1}–{Math.min(rows.length, (at + 1) * size)} of {rows.length.toLocaleString()}
                    <Button
                        variant="default"
                        size="icon-xs"
                        title="Previous page"
                        disabled={at === 0}
                        onClick={() => setPage(at - 1)}
                    >
                        <IconChevronLeft />
                    </Button>
                    <Button
                        variant="default"
                        size="icon-xs"
                        title="Next page"
                        disabled={at >= pages - 1}
                        onClick={() => setPage(at + 1)}
                    >
                        <IconChevronRight />
                    </Button>
                </div>
            )}
        </div>
    )
}

export function sortedOrder(rows: unknown[][], ci: number, desc: boolean): number[] {
    const empty = (v: unknown): boolean => v === null || v === undefined || v === ''
    return rows
        .map((_, i) => i)
        .sort((a, b) => {
            const x = rows[a]![ci],
                y = rows[b]![ci]
            if (empty(x) || empty(y)) {
                return Number(empty(x)) - Number(empty(y))
            }
            const c =
                typeof x === 'number' && typeof y === 'number'
                    ? x - y
                    : String(x).localeCompare(String(y), undefined, { numeric: true })
            return desc ? -c : c
        })
}

export function textOn(bg: string): string {
    const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(bg.trim())
    if (!m) {
        return 'white'
    }
    const h =
        m[1]!.length === 3
            ? m[1]!
                  .split('')
                  .map((c) => c + c)
                  .join('')
            : m[1]!
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
    return 0.299 * r! + 0.587 * g! + 0.114 * b! > 0.6 ? '#1f2328' : 'white'
}

export const safeHref = (u: string): boolean => /^https?:\/\//i.test(u) || (u.startsWith('/') && !u.startsWith('//'))
