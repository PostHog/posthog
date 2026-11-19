import { useMemo, useRef } from 'react'

import { Heatmap, LineChart, type HeatmapCellDatum } from '@posthog/quill-charts'

import { useDisplayChartTheme } from '../editor/display'
import { EmptyData } from './EmptyData'
import type { DataFrame } from './frame'
import type { RetentionOptions as O } from './options'
import type { VizProps } from './registry'

export type Retention = { periods: string[]; cohorts: { label: string; size: number | null; pct: (number | null)[] }[] }

const isPercent = (u?: string): boolean => u === '%' || u === 'percent'

export function toRetention(frames: DataFrame[], panelUnit?: string): Retention | null {
    const f = frames.find(
        (x) =>
            x.fields.some((y) => y.type === 'string' || y.type === 'time') && x.fields.some((y) => y.type === 'number')
    )
    if (!f) {
        return null
    }
    const label = f.fields.find((x) => x.type === 'string') ?? f.fields.find((x) => x.type === 'time')!
    const nums = f.fields.filter((x) => x.type === 'number')
    const sizeField = nums.find((x) => /size/i.test(x.name))
    const periods = nums.filter((x) => x !== sizeField)
    if (!periods.length) {
        return null
    }
    const num = (v: unknown): number | null =>
        v === null || v === undefined || v === '' || Number.isNaN(Number(v)) ? null : Number(v)
    const cohorts = label.values.map((l, i) => {
        const size = sizeField ? num(sizeField.values[i]) : num(periods[0]!.values[i])
        const pct = periods.map((p) => {
            const v = num(p.values[i])
            if (v === null || isPercent(p.config?.unit ?? panelUnit)) {
                return v
            }
            return size ? (v / size) * 100 : null
        })
        return {
            label: label.type === 'time' ? new Date(Number(l)).toISOString().slice(0, 10) : String(l ?? ''),
            size,
            pct,
        }
    })
    return { periods: periods.map((p) => p.config?.displayName ?? p.name), cohorts }
}

const lastOf = (pct: (number | null)[]): number => pct.reduce<number>((at, v, j) => (v !== null ? j : at), -1)

export function meanRow(r: Retention, skipInProgress = false, weighted = false): Retention['cohorts'][number] {
    const avg = (xs: (number | null)[], ws?: (number | null)[]): number | null => {
        let sum = 0,
            n = 0
        xs.forEach((x, i) => {
            const w = ws ? (ws[i] ?? 0) : 1
            if (x !== null && w) {
                sum += x * w
                n += w
            }
        })
        return n ? sum / n : null
    }
    const size = avg(r.cohorts.map((c) => c.size))
    const cell = (c: Retention['cohorts'][number], j: number): number | null =>
        skipInProgress && j > 0 && j === lastOf(c.pct) ? null : (c.pct[j] ?? null)
    const weights = weighted ? r.cohorts.map((c) => c.size) : undefined
    return {
        label: 'Mean',
        size: size === null ? null : Math.round(size),
        pct: r.periods.map((_, j) =>
            avg(
                r.cohorts.map((c) => cell(c, j)),
                weights
            )
        ),
    }
}

const MEAN_COLOR = '#7950f2'
const pctText = (v: number): string => `${v.toFixed(1)}%`

export function RetentionViz({ frames, panel, options, onDrill }: VizProps<O>): React.JSX.Element {
    const theme = useDisplayChartTheme()
    const unit = panel.fieldConfig?.unit ?? undefined
    const onDrillRef = useRef(onDrill)
    onDrillRef.current = onDrill
    const m = useMemo(() => {
        const r = toRetention(frames, unit)
        if (!r || !r.cohorts.length) {
            return null
        }
        const hasMean = options.mean && r.cohorts.length > 1
        const rows = [...r.cohorts]
            .reverse()
            .concat(hasMean ? [meanRow(r, options.incomplete, options.meanBy === 'weighted')] : [])
        const last = rows.map((c) => lastOf(c.pct))
        const cellStyle = (
            c: HeatmapCellDatum
        ): { outlined?: boolean | undefined; filled?: boolean | undefined; color?: string | undefined } => {
            const mean = hasMean && c.yIndex === rows.length - 1
            const v = rows[c.yIndex]?.pct[c.xIndex]
            return {
                ...(mean ? { color: MEAN_COLOR } : {}),
                ...(v === 0 ? { filled: true } : {}),
                ...(options.incomplete && !mean && c.xIndex > 0 && c.xIndex === last[c.yIndex]
                    ? { outlined: true }
                    : {}),
            }
        }
        const cellLabel = (c: HeatmapCellDatum): string | null =>
            rows[c.yIndex]?.pct[c.xIndex] == null ? null : pctText(c.value)
        const cellClick = (c: HeatmapCellDatum): void => {
            if (hasMean && c.yIndex === rows.length - 1) {
                return
            }
            const index = r.cohorts.length - 1 - c.yIndex,
                cohort = r.cohorts[index]!
            onDrillRef.current?.({
                refId: frames[0]?.refId,
                cohort: { index, label: cohort.label, period: c.xIndex },
                value: cohort.pct[c.xIndex],
                row: { cohort: cohort.label, period: r.periods[c.xIndex], size: cohort.size },
            })
        }
        return { r, rows, cellStyle, cellLabel, cellClick }
    }, [frames, unit, options.mean, options.incomplete, options.meanBy])
    if (!m) {
        return <EmptyData />
    }
    if (options.display === 'curve') {
        const mean = options.mean ? meanRow(m.r, options.incomplete, options.meanBy === 'weighted') : undefined
        const nan = (xs: (number | null)[]): number[] => xs.map((v) => (v === null ? NaN : v))
        return (
            <LineChart
                className="min-h-0 flex-1"
                theme={theme}
                labels={m.r.periods}
                series={
                    [
                        ...m.r.cohorts.map((c, i) => ({
                            key: `c${i}`,
                            label: c.label,
                            data: nan(c.pct),
                            color: theme.colors[i % theme.colors.length],
                            stroke: { width: 1 },
                        })),
                        ...(mean
                            ? [
                                  {
                                      key: 'mean',
                                      label: 'Mean',
                                      data: nan(mean.pct),
                                      color: MEAN_COLOR,
                                      stroke: { width: 3 },
                                  },
                              ]
                            : []),
                    ] as never
                }
                onPointClick={
                    onDrill
                        ? (((d: any) => {
                              const i = Number(String(d.series.key).slice(1))
                              const cohort = m.r.cohorts[i]
                              if (cohort) {
                                  onDrill({
                                      refId: frames[0]?.refId,
                                      cohort: { index: i, label: cohort.label, period: d.dataIndex },
                                      value: d.value,
                                  })
                              }
                          }) as never)
                        : undefined
                }
                config={
                    {
                        showGrid: true,
                        yTickFormatter: (v: number) => `${Math.round(v)}%`,
                        valueDomain: { min: 0, max: 100 },
                        tooltip: { valueFormatter: pctText },
                        legend: { show: m.r.cohorts.length <= 12, position: 'bottom' },
                    } as never
                }
            />
        )
    }
    return (
        <Heatmap
            className="min-h-0 flex-1"
            theme={theme}
            xLabels={m.r.periods}
            yLabels={m.rows.map((c) =>
                options.showSize && c.size !== null ? `${c.label}  ${c.size.toLocaleString()}` : c.label
            )}
            cells={m.rows.map((c) => c.pct.map((v) => v ?? 0))}
            config={{
                colorScale: 'linear',
                cellLabel: m.cellLabel,
                cellStyle: m.cellStyle,
                tooltip: { valueFormatter: pctText },
            }}
            onCellClick={onDrill ? m.cellClick : undefined}
        />
    )
}
