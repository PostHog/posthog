import { useRef, useState } from 'react'

import { IconCopy } from '@posthog/icons'
import {
    TimeSeriesComboChart,
    TimeSeriesLineChart,
    TooltipFooter,
    ValueBand,
    TooltipSurface,
    TooltipSwatch,
    ciRanges,
    movingAverage,
    type TooltipContext,
} from '@posthog/quill-charts'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { useDisplayChartTheme } from '../editor/display'
import { goalLinesFor, thresholdBands, tooltipFor, withOverrides, xAxisFor, yAxisFor } from './chartCommon'
import { colorize } from './colors'
import { bucketOf, seriesOrigin } from './drilldown'
import { DRILL_KEY, useDrillKey } from './drillKey'
import { parseDuration } from './duration'
import { EmptyData } from './EmptyData'
import { formatValue } from './format'
import { alignPrevious, drawnIncomplete, incompleteMode, toXSeries } from './frames'
import { legendClick } from './legend'
import type { TimeseriesOptions as O } from './options'
import type { VizProps } from './registry'

export function TimeseriesViz({
    frames,
    panel,
    options,
    range,
    timezone,
    onTimeRange,
    onDrill,
}: VizProps<O>): React.JSX.Element {
    const theme = useDisplayChartTheme()
    const drillKey = useDrillKey(!!onDrill)
    const [hidden, setHidden] = useState<Set<string>>(new Set())
    const [search, setSearch] = useState({ at: '', q: '' })
    const pins = useRef({ n: 0, pinned: false })
    const prevMode = options.previous
    const shiftMs =
        panel.compare === 'previous'
            ? range && range.to - range.from
            : panel.compare
              ? parseDuration(panel.compare)
              : undefined
    const { frames: aligned, pairs } = alignPrevious(
        prevMode === 'hidden' ? frames.filter((f) => !f.meta?.previous) : frames,
        shiftMs
    )
    const { labels, series: inQueryOrder, categorical } = toXSeries(aligned, range)
    const unordered = inQueryOrder.map((s, pos) => ({ ...s, pos }))
    const total = (s: (typeof unordered)[number]): number =>
        s.data.reduce((a: number, v) => a + (Number.isFinite(v) ? Number(v) : 0), 0)
    const raw =
        options.seriesOrder === 'name'
            ? [...unordered].sort((a, b) =>
                  a.label.localeCompare(b.label, undefined, { numeric: true, sensitivity: 'base' })
              )
            : options.seriesOrder === 'total'
              ? [...unordered].sort((a, b) => total(b) - total(a))
              : unordered
    const x = categorical
        ? { interval: 'day' as const, tickFormatter: (v: string) => v, labelFormatter: (v: string) => v }
        : xAxisFor(labels, timezone)
    const colored = colorize(panel, withOverrides(panel, raw), theme.colors)
    const series =
        prevMode !== 'dashed' || !aligned.some((f) => f.meta?.previous)
            ? colored
            : colored.map((s) => {
                  const [fi, ni] = s.key.split(':')
                  if (!aligned[Number(fi)]?.meta?.previous) {
                      return s
                  }
                  const ci = pairs.get(Number(fi))
                  const cur = ci === undefined ? undefined : colored.find((x) => x.key === `${ci}:${ni}`)
                  return {
                      ...s,
                      color: cur?.color ?? s.color,
                      o: { ...s.o, style: 'line' as const, stack: false, fill: 0, dash: s.o?.dash ?? [6, 4] },
                  }
              })
    if (!series.length || !labels.length) {
        return <EmptyData />
    }
    const prevFrames = new Set(pairs.keys())
    const overlaid = series.filter((s) => !prevFrames.has(Number(s.key.split(':')[0])) && !hidden.has(s.key))
    const ma = options.movingAverage && options.movingAverage > 1 ? options.movingAverage : 0
    const trend = options.trendLine && options.trendLine !== 'none' ? options.trendLine : undefined
    const level =
        options.confidence && options.confidence > 0 && options.confidence < 100 ? options.confidence / 100 : 0
    const overlays = {
        ...(ma
            ? {
                  movingAverage: overlaid.map((s) => ({
                      seriesKey: s.key,
                      window: ma,
                      label: `${s.label} (${ma}-point average)`,
                  })),
              }
            : {}),
        ...(trend
            ? { trendLines: overlaid.map((s) => ({ seriesKey: s.key, kind: trend, label: `${s.label} (trend)` })) }
            : {}),
        ...(level
            ? {
                  confidenceIntervals: overlaid.map((s) => {
                      const [lower, upper] = ciRanges(s.data.map(Number), level)
                      return { seriesKey: s.key, lower, upper }
                  }),
              }
            : {}),
    }
    const table = options.legend !== 'none' && !!options.legendCalcs?.length
    const unitOf = new Map(series.map((s) => [s.key, s.o?.unit ?? panel.fieldConfig?.unit ?? s.unit]))
    const styleOf = (s: (typeof series)[number]): 'line' | 'bars' | 'points' => s.o?.style ?? options.style
    const bars = series.some((s) => styleOf(s) === 'bars')
    const right = series.filter((s) => s.o?.axis === 'right')
    const unit = series.find((s) => s.o?.axis !== 'right')?.unit ?? series[0]?.unit
    const rightUnit = right[0]?.o?.unit ?? right[0]?.unit
    const fillOf = (s: (typeof series)[number]): number =>
        s.o?.fill ??
        (bars && styleOf(s) !== 'bars' ? (options.area ? 0.25 : 0) : options.area || options.stack ? 0.25 : 0)
    const mode = incompleteMode(panel)
    const partial = categorical ? -1 : drawnIncomplete(panel, aligned, labels.map(Date.parse))
    const strokeOf = (
        s: (typeof series)[number]
    ):
        | { bars: { hatch: boolean }[]; stroke?: undefined }
        | {
              stroke: {
                  partial?: { fromIndex: number; pattern: number[] } | undefined
                  width?: number | undefined
                  pattern?: number[] | undefined
              }
              bars?: undefined
          }
        | { bars?: undefined; stroke?: undefined } => {
        const from = partial < 0 || prevFrames.has(Number(s.key.split(':')[0])) ? -1 : partial
        const pattern = s.o?.dash?.length ? s.o.dash : undefined
        const width = s.o?.width ?? (styleOf(s) === 'points' ? 0 : options.lineWidth)
        if (from >= 0 && styleOf(s) === 'bars') {
            return { bars: s.data.map((_, j) => ({ hatch: j >= from })) }
        }
        return pattern || width !== undefined || from >= 0
            ? {
                  stroke: {
                      ...(pattern ? { pattern } : {}),
                      ...(width !== undefined ? { width } : {}),
                      ...(from >= 0
                          ? {
                                partial: {
                                    fromIndex: from,
                                    pattern: [6, 4],
                                },
                            }
                          : {}),
                  },
              }
            : {}
    }
    const filled = series.length ? series[0]!.data.map((_, i) => series.some((x) => Number.isFinite(x.data[i]))) : []
    const common = (
        s: (typeof series)[number]
    ):
        | {
              points?: { radius: number } | undefined
              yAxisId?: string | undefined
              bars: { hatch: boolean }[]
              stroke?: undefined
              key: string
              label: string
              color: string
              data: number[]
          }
        | {
              points?: { radius: number } | undefined
              yAxisId?: string | undefined
              stroke: {
                  partial?: { fromIndex: number; pattern: number[] } | undefined
                  width?: number | undefined
                  pattern?: number[] | undefined
              }
              bars?: undefined
              key: string
              label: string
              color: string
              data: number[]
          }
        | {
              points?: { radius: number } | undefined
              yAxisId?: string | undefined
              bars?: undefined
              stroke?: undefined
              key: string
              label: string
              color: string
              data: number[]
          } => ({
        key: s.key,
        label: s.label,
        color: s.color,
        data: (s.o?.negate ? s.data.map((v) => -v) : s.data).map((v, i) =>
            options.stack && s.o?.stack !== false && !Number.isFinite(v) && filled[i] ? 0 : v
        ),
        ...strokeOf(s),
        ...(s.o?.axis === 'right' ? { yAxisId: 'right' } : {}),
        ...(styleOf(s) === 'points' ? { points: { radius: 3 } } : options.points ? { points: { radius: 2 } } : {}),
    })
    const fc = panel.fieldConfig
    const visible = series
        .filter((s) => !hidden.has(s.key) && s.o?.axis !== 'right')
        .flatMap((s) => s.data.filter(Number.isFinite))
    const negative = series.some((s) => s.o?.axis !== 'right' && s.data.some((v) => v < 0))
    const pct = !!(options.stack && options.percent)
    const left = {
        ...(pct
            ? yAxisFor({ ...panel, fieldConfig: { ...fc, unit: 'percentunit', decimals: 0 } }, 'percentunit')
            : yAxisFor(panel, unit)),
        ...(negative && fc?.min == null ? { startAtZero: false } : {}),
        scale: options.scale,
        ...(options.axisLabel ? { label: options.axisLabel } : {}),
        ...(fc?.min == null && fc?.softMin != null && visible.length ? { min: Math.min(fc.softMin, ...visible) } : {}),
        ...(fc?.max == null && fc?.softMax != null && visible.length ? { max: Math.max(fc.softMax, ...visible) } : {}),
    }
    const yAxis = right.length
        ? [
              { ...left, id: 'left', position: 'left' as const },
              {
                  ...yAxisFor({ ...panel, fieldConfig: { ...panel.fieldConfig, unit: rightUnit } }, rightUnit),
                  ...(options.axisLabelRight ? { label: options.axisLabelRight } : {}),
                  id: 'right',
                  position: 'right' as const,
              },
          ]
        : left
    const ts = options.thresholdStyle
    const bands = ts.endsWith('area') ? thresholdBands(panel).map((b) => <ValueBand key={b.from} {...b} />) : null
    const config = {
        curve: options.curve,
        showGrid: true,
        showCrosshair: true,
        xAxis: { interval: x.interval, tickFormatter: x.tickFormatter },
        yAxis,
        tooltip: {
            ...tooltipFor(panel, unit),
            labelFormatter: x.labelFormatter,
            enabled: options.tooltip !== 'none',
            sortedByValue: options.tooltipSort === 'none' ? false : options.tooltipSort,
            pinnable: !drillKey,
        },
        goalLines: ts === 'area' ? [] : goalLinesFor(panel, ts.startsWith('line') ? 'solid' : 'dashed'),
        connectNulls: !!options.connectNulls,
        ...(options.showValues
            ? { valueLabels: { formatter: (v: number) => tooltipFor(panel, unit).valueFormatter(v) } }
            : {}),
        legend: {
            show: options.legend !== 'none' && (table || series.length > 1),
            position: options.legend === 'none' ? ('bottom' as const) : options.legend,
            interactive: true,
            hiddenKeys: [...hidden],
            onToggleSeries: (key: string, off: boolean) =>
                setHidden((h) => {
                    const n = new Set(h)
                    off ? n.add(key) : n.delete(key)
                    return n
                }),
            onSetHiddenSeries: (keys: string[]) => setHidden(new Set(keys)),
            renderItem: (node: React.ReactNode, item: { key: string }) => (item.key === PIN_AID ? null : node),
            ...(table
                ? {
                      table: {
                          values: options.legendCalcs!,
                          ...(options.legendSort
                              ? {
                                    defaultSort: {
                                        by:
                                            options.legendSort === 'name'
                                                ? ('label' as const)
                                                : (options.legendSort as never),
                                        descending: options.legendSortDesc ?? true,
                                    },
                                }
                              : {}),
                          valueFormatter: (v: number, item: { key: string }) =>
                              formatValue(v, unitOf.get(item.key), panel.fieldConfig?.decimals),
                      },
                  }
                : {}),
        },
    }
    const onPointClick = onDrill
        ? (d: { series: { key: string; label?: string }; dataIndex: number; value: number }) => {
              const s = series.find((x) => x.key === d.series.key)
              if (!s) {
                  return
              }
              const o = seriesOrigin(aligned, s.key)
              onDrill({
                  refId: o.refId,
                  series: { name: s.label, labels: o.labels },
                  value: d.value,
                  ...(categorical ? { category: labels[d.dataIndex] } : { time: bucketOf(labels, d.dataIndex) }),
              })
          }
        : undefined
    const keys = series.map((s) => s.key)
    const dim = (
        k: string,
        node: React.ReactNode
    ): string | number | boolean | React.JSX.Element | Iterable<React.ReactNode> | null | undefined =>
        hidden.has(k) ? <span className="opacity-40">{node}</span> : node
    const tooltip = (ctx: TooltipContext): React.JSX.Element => {
        const rows = series.flatMap((s) => {
            const v = s.data[ctx.dataIndex]
            return v != null && Number.isFinite(v)
                ? [
                      {
                          series: { key: s.key, label: s.label, data: s.data },
                          value: v,
                          color: hidden.has(s.key) ? `color-mix(in srgb, ${s.color} 35%, transparent)` : s.color,
                      },
                  ]
                : []
        })
        const fmt = config.tooltip.valueFormatter
        const pinned = !!ctx.isPinned
        if (!pinned && pins.current.pinned) {
            pins.current = { n: pins.current.n + 1, pinned: false }
        }
        if (pinned) {
            pins.current.pinned = true
        }
        const at = `${pins.current.n}`
        const q = pinned && search.at === at ? search.q.toLowerCase() : ''
        const order = options.tooltipSort
        const sorted =
            order === 'none'
                ? rows
                : [...rows].sort((a, b) => (order === 'asc' ? a.value - b.value : b.value - a.value))
        const near =
            options.tooltip === 'single' && !pinned
                ? (ctx.hoveredSeriesKey ??
                  (ctx.hoverPosition &&
                      ctx.seriesData
                          .filter((d) => d.yPixel != null)
                          .sort(
                              (a, b) =>
                                  Math.abs(a.yPixel! - ctx.hoverPosition!.y) -
                                  Math.abs(b.yPixel! - ctx.hoverPosition!.y)
                          )[0]?.series.key))
                : undefined
        const shownRows = near ? sorted.filter((r) => r.series.key === near) : sorted
        const list = q ? shownRows.filter((r) => (r.series.label ?? r.series.key).toLowerCase().includes(q)) : shownRows
        return (
            <TooltipSurface>
                <div className="mb-1 font-semibold opacity-60">
                    {config.tooltip.labelFormatter(ctx.label)}
                    {partial >= 0 && ctx.dataIndex >= partial
                        ? Date.parse(labels[ctx.dataIndex]!) > Date.now()
                            ? ' (future)'
                            : mode === 'estimate'
                              ? ' (estimate)'
                              : ' (in progress)'
                        : ''}
                </div>
                {pinned && rows.length > 8 && (
                    <input
                        autoFocus
                        className="mb-1 w-full min-w-0 rounded border border-current/25 bg-transparent px-1.5 py-0.5 outline-none placeholder:opacity-50 focus:border-current/50"
                        placeholder={`Filter ${rows.length} series`}
                        size={1}
                        value={search.at === at ? search.q : ''}
                        onChange={(e) => setSearch({ at, q: e.target.value })}
                    />
                )}
                <div
                    className="grid grid-cols-[auto_minmax(0,1fr)_auto]"
                    style={{ maxHeight: '14rem', overflowY: 'auto', scrollbarWidth: 'none' }}
                >
                    {list.map((r) => (
                        <div
                            key={r.series.key}
                            className={`group/row col-span-3 grid min-w-0 grid-cols-subgrid items-center gap-2 rounded px-1.5 py-0.5 ${pinned ? 'cursor-pointer transition-colors duration-150 hover:bg-current/10' : ''}`}
                            onClick={
                                pinned
                                    ? (e) =>
                                          !getSelection()?.toString() &&
                                          setHidden((h) =>
                                              legendClick(h, keys, r.series.key, e.metaKey || e.ctrlKey || e.shiftKey)
                                          )
                                    : undefined
                            }
                        >
                            <TooltipSwatch color={r.color} />
                            <span className="flex min-w-0 items-center gap-1">
                                <span className={`truncate ${hidden.has(r.series.key) ? 'opacity-40' : ''}`}>
                                    {r.series.label}
                                </span>
                                {pinned && (
                                    <button
                                        className="hidden shrink-0 opacity-60 group-hover/row:inline"
                                        title="Copy name"
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            copy(r.series.label ?? r.series.key)
                                        }}
                                    >
                                        <IconCopy className="size-3" />
                                    </button>
                                )}
                            </span>
                            <strong className="justify-self-end tabular-nums">{dim(r.series.key, fmt(r.value))}</strong>
                        </div>
                    ))}
                    {pinned && !list.length && (
                        <div className="col-span-3 px-1.5 py-0.5 opacity-60">No series match</div>
                    )}
                </div>
                {pinned ? (
                    <TooltipFooter>
                        <div className="flex items-center justify-center gap-3">
                            <span>Click: only this · ⌘-click: toggle</span>
                            {hidden.size > 0 && (
                                <button
                                    className="underline-offset-2 hover:underline"
                                    onClick={() => setHidden(new Set())}
                                >
                                    Show all
                                </button>
                            )}
                            <button
                                className="underline-offset-2 hover:underline"
                                onClick={() =>
                                    copy(
                                        [
                                            config.tooltip.labelFormatter(ctx.label),
                                            ...sorted.map((r) => `${r.series.label}\t${fmt(r.value)}`),
                                        ].join('\n')
                                    )
                                }
                            >
                                Copy all
                            </button>
                        </div>
                    </TooltipFooter>
                ) : (
                    (hidden.size > 0 || onDrill) && (
                        <TooltipFooter>
                            {[
                                hidden.size > 0 && 'Click to change which series show',
                                onDrill && `${DRILL_KEY}-click to drill down`,
                            ]
                                .filter(Boolean)
                                .join(' · ')}
                        </TooltipFooter>
                    )
                )}
            </TooltipSurface>
        )
    }
    const shown = series.filter((s) => !hidden.has(s.key))
    const pinAid = (all: Record<string, unknown>[]): Record<string, unknown>[] =>
        shown.length === 1 && hidden.size
            ? [
                  ...all,
                  {
                      ...all.find((x) => x.key === shown[0]!.key)!,
                      key: PIN_AID,
                      label: '',
                      color: 'transparent',
                      visibility: { valueLabel: false },
                  },
              ]
            : all
    const onZoom =
        !categorical && onTimeRange
            ? (d: { startIndex: number; endIndex: number }) => {
                  const [a, b] = [Math.min(d.startIndex, d.endIndex), Math.max(d.startIndex, d.endIndex)]
                  onTimeRange(Date.parse(labels[a]!), bucketOf(labels, b)?.to ?? Date.parse(labels[b]!))
              }
            : undefined
    const unstackedFills = series.filter((s) => fillOf(s) > 0).length >= 2 && !options.stack
    if (!bars && !unstackedFills) {
        return (
            <TimeSeriesLineChart
                className="min-h-0 flex-1"
                theme={theme}
                labels={labels}
                config={{ ...config, ...overlays, percentStackView: pct, xScale: categorical ? 'index' : 'time' }}
                onDateRangeZoom={onZoom}
                tooltip={tooltip}
                onPointClick={onPointClick as never}
                series={
                    pinAid(
                        series.map((s) =>
                            s.o?.stack === false || fillOf(s) === 0
                                ? { ...common(s), type: 'line' }
                                : {
                                      ...common(s),
                                      type: 'area',
                                      fill: { opacity: fillOf(s), gradient: !!options.gradient },
                                  }
                        )
                    ) as never
                }
            >
                {bands}
            </TimeSeriesLineChart>
        )
    }
    return (
        <TimeSeriesComboChart
            className="min-h-0 flex-1"
            theme={theme}
            labels={labels}
            config={{
                ...config,
                ...(overlays.trendLines ? { trendLines: overlays.trendLines } : {}),
                barLayout: options.stack ? (options.percent ? 'percent' : 'stacked') : 'grouped',
                ...(left.min !== undefined || left.max !== undefined
                    ? {
                          valueDomain: {
                              ...(left.min !== undefined ? { min: left.min } : {}),
                              ...(left.max !== undefined ? { max: left.max } : {}),
                          },
                      }
                    : {}),
            }}
            tooltip={tooltip}
            onPointClick={onPointClick as never}
            series={
                pinAid([
                    ...series.map((s) => {
                        const style = styleOf(s),
                            fill = fillOf(s)
                        return {
                            ...common(s),
                            type: style === 'bars' ? 'bar' : fill > 0 ? 'area' : 'line',
                            ...(style !== 'bars' && fill > 0
                                ? { fill: { opacity: fill, gradient: !!options.gradient } }
                                : {}),
                        }
                    }),
                    ...(ma
                        ? overlaid.map((s) => ({
                              key: `${s.key}~ma`,
                              label: `${s.label} (${ma}-point average)`,
                              color: s.color,
                              data: movingAverage(s.data.map(Number), ma),
                              type: 'line',
                              overlay: true,
                              stroke: { pattern: [2, 3] },
                          }))
                        : []),
                ]) as never
            }
        >
            {bands}
        </TimeSeriesComboChart>
    )
}

const PIN_AID = '__pin'

const copy = (text: string): void => void copyToClipboard(text)
