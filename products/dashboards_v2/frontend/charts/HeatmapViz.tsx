import { useMemo } from 'react'

import { Heatmap, type HeatmapCellDatum } from '@posthog/quill-charts'

import { useDisplayChartTheme } from '../editor/display'
import { colorToken, fieldOverride, xAxisFor } from './chartCommon'
import { byValue, valueColor } from './colors'
import { bucketOf } from './drilldown'
import { EmptyData } from './EmptyData'
import { formatValue } from './format'
import type { DataFrame } from './frame'
import { hasTime, toTable, toTimeSeries } from './frames'
import type { HeatmapOptions as O } from './options'
import type { VizProps } from './registry'

export type Grid = { x: string[]; y: string[]; cells: (number | null)[][]; long: boolean }

export function toGrid(frames: DataFrame[]): Grid | null {
    if (frames.length > 1 || frames[0]?.fields.some((x) => x.labels && Object.keys(x.labels).length)) {
        const t = toTable(frames)
        frames = [
            { fields: t.columns.map((c, i) => ({ name: c.name, type: c.type, values: t.rows.map((r) => r[i]) })) },
        ]
    }
    const f = frames[0]
    if (!f || f.fields.length < 2) {
        return null
    }
    const order = (vals: unknown[]): string[] => {
        const seen = [...new Set(vals.map((v) => String(v ?? '')))]
        return seen.every((v) => v !== '' && Number.isFinite(Number(v)))
            ? seen.sort((a, b) => Number(a) - Number(b))
            : seen
    }
    const num = (v: unknown): number | null =>
        v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? null : Number(v)
    const first = f.fields[0]!
    const long = f.fields.length >= 3 && new Set(first.values.map(String)).size < first.values.length
    if (long) {
        const [xf, yf] = f.fields as [typeof first, typeof first]
        const vf = f.fields.slice(2).find((x) => x.type === 'number') ?? f.fields[2]!
        const x = order(xf.values),
            y = order(yf.values)
        const cells = y.map(() => x.map((): number | null => null))
        xf.values.forEach((xv, i) => {
            cells[y.indexOf(String(yf.values[i] ?? ''))]![x.indexOf(String(xv ?? ''))] = num(vf.values[i])
        })
        return { x, y, cells, long: true }
    }
    const label = f.fields.find((x) => x.type !== 'number') ?? first
    const cols = f.fields.filter((x) => x !== label && x.type === 'number')
    if (!cols.length) {
        return null
    }
    return {
        x: cols.map((c) => c.config?.displayName ?? c.name),
        y: label.values.map((v) => String(v ?? '')),
        cells: label.values.map((_, i) => cols.map((c) => num(c.values[i]))),
        long: false,
    }
}

export function HeatmapViz(props: VizProps<O>): React.JSX.Element {
    return hasTime(props.frames) ? <TimeHeatmap {...props} /> : <CategoryHeatmap {...props} />
}

function CategoryHeatmap({ frames, panel, options, onDrill }: VizProps<O>): React.JSX.Element {
    const theme = useDisplayChartTheme()
    const g = toGrid(frames)
    const unit = panel.fieldConfig?.unit
    const fmt = (v: number): string => formatValue(v, unit, panel.fieldConfig?.decimals)
    const name = (l: string): string => fieldOverride(panel, l)?.displayName ?? l
    const color = panel.fieldConfig?.color
    const rows = g ? [...g.cells].reverse() : []
    const max = Math.max(0, ...rows.flat().map((v) => v ?? 0))
    const cellStyle = useMemo(
        () => (c: HeatmapCellDatum) => ({
            ...(byValue(color?.mode) ? { color: valueColor(panel, c.value, 0, max) } : {}),
            ...(rows[c.yIndex]?.[c.xIndex] === 0 ? { filled: true } : {}),
        }),
        [panel, max, frames]
    )
    const cellLabel = useMemo(
        () =>
            options.showValues
                ? (c: HeatmapCellDatum) => (rows[c.yIndex]?.[c.xIndex] == null ? null : fmt(c.value))
                : undefined,
        [options.showValues, frames, panel]
    )
    if (!g || !g.y.length) {
        return <EmptyData />
    }
    return (
        <Heatmap
            className="min-h-0 flex-1"
            theme={theme}
            xLabels={g.long ? g.x : g.x.map(name)}
            yLabels={[...g.y].reverse().map(name)}
            cells={rows.map((r) => r.map((v) => v ?? 0))}
            config={{
                colorScale: options.colorScale,
                color:
                    color?.mode === 'fixed' || color?.mode === 'shades'
                        ? colorToken(color.fixedColor ?? 'blue')
                        : undefined,
                cellStyle,
                cellLabel,
                tooltip: { valueFormatter: fmt },
            }}
            onCellClick={
                onDrill
                    ? (c) => {
                          const y = [...g.y].reverse()[c.yIndex]!
                          onDrill({
                              refId: frames[0]?.refId,
                              category: y,
                              value: c.value,
                              row: { x: g.x[c.xIndex], y },
                          })
                      }
                    : undefined
            }
        />
    )
}

function TimeHeatmap({ frames, panel, options, timezone, onDrill }: VizProps<O>): React.JSX.Element {
    const theme = useDisplayChartTheme()
    const { labels, series } = toTimeSeries(frames)
    const le = frames.flatMap((f) => f.fields.filter((x) => x.type === 'number').map((x) => x.labels?.le))
    const isHistogram = le.length === series.length && le.every((x) => x !== undefined)
    let rows = series.map((s, i) => ({
        label: isHistogram ? le[i]! : s.label,
        bound: isHistogram ? (le[i] === '+Inf' ? Infinity : Number(le[i])) : i,
        data: s.data.map((v) => (Number.isNaN(v) ? 0 : v)),
    }))
    if (isHistogram) {
        rows.sort((a, b) => a.bound - b.bound)
        rows = rows.map((r, i) =>
            i === 0 ? r : { ...r, data: r.data.map((v, j) => Math.max(0, v - rows[i - 1]!.data[j]!)) }
        )
    }
    const unit = panel.fieldConfig?.unit
    const x = xAxisFor(labels, timezone)
    const color = panel.fieldConfig?.color
    const max = Math.max(0, ...rows.flatMap((r) => r.data))
    const cellStyle = useMemo(
        () =>
            byValue(color?.mode) ? (c: HeatmapCellDatum) => ({ color: valueColor(panel, c.value, 0, max) }) : undefined,
        [panel, max]
    )
    if (!series.length || !labels.length) {
        return <EmptyData />
    }
    return (
        <Heatmap
            className="min-h-0 flex-1"
            theme={theme}
            xLabels={labels}
            yLabels={rows.map((r) =>
                isHistogram && unit && Number.isFinite(r.bound) ? formatValue(r.bound, unit) : r.label
            )}
            cells={rows.map((r) => r.data)}
            config={{
                colorScale: options.colorScale,
                color:
                    color?.mode === 'fixed' || color?.mode === 'shades'
                        ? colorToken(color.fixedColor ?? 'blue')
                        : undefined,
                cellStyle,
                xTickFormatter: (l) => x.tickFormatter(l),
                tooltip: {
                    labelFormatter: x.labelFormatter,
                    valueFormatter: (v) => formatValue(v, undefined, panel.fieldConfig?.decimals),
                },
            }}
            onCellClick={
                onDrill
                    ? (c) =>
                          onDrill({
                              refId: frames[0]?.refId,
                              series: { name: c.yLabel },
                              category: c.yLabel,
                              value: c.value,
                              time: bucketOf(labels, c.xIndex),
                          })
                    : undefined
            }
        />
    )
}
