import { BoxPlot, type BoxPlotDatum } from '@posthog/quill-charts'

import { useDisplayChartTheme } from '../editor/display'
import { tooltipFor, withOverrides, xAxisFor } from './chartCommon'
import { colorize } from './colors'
import { bucketOf } from './drilldown'
import { EmptyData } from './EmptyData'
import type { DataFrame, Field } from './frame'
import type { BoxPlotOptions as O } from './options'
import type { VizProps } from './registry'

const ROLES: Record<keyof Omit<BoxPlotDatum, 'day' | 'whiskerMin' | 'whiskerMax'>, RegExp> = {
    min: /^(min|minimum|p0)$/i,
    p25: /^(p25|q1|lower_quartile)$/i,
    median: /^(median|p50|q2)$/i,
    mean: /^(mean|avg|average)$/i,
    p75: /^(p75|q3|upper_quartile)$/i,
    max: /^(max|maximum|p100)$/i,
}

export function toBoxes(
    frames: DataFrame[]
): { labels: string[]; series: { label: string; data: (BoxPlotDatum | null)[] }[]; hasMean: boolean } | null {
    const labels: string[] = []
    const at = new Map<string, number>()
    let hasMean = false
    const parsed = frames.flatMap((f) => {
        const col = (k: keyof typeof ROLES): Field | undefined =>
            f.fields.find((x) => x.type === 'number' && ROLES[k].test(x.name))
        const cols = {
            min: col('min'),
            p25: col('p25'),
            median: col('median'),
            mean: col('mean'),
            p75: col('p75'),
            max: col('max'),
        }
        if (!cols.min || !cols.p25 || !cols.median || !cols.p75 || !cols.max) {
            return []
        }
        hasMean ||= !!cols.mean
        const x = f.fields.find((y) => y.type === 'time') ?? f.fields.find((y) => y.type === 'string')
        const keys = (x?.values ?? f.fields[0]!.values.map((_, i) => String(i))).map((v) =>
            x?.type === 'time' ? new Date(Number(v)).toISOString() : String(v ?? '')
        )
        for (const k of keys) {
            if (!at.has(k)) {
                at.set(k, labels.length)
                labels.push(k)
            }
        }
        return [{ f, cols, keys }]
    })
    if (!parsed.length) {
        return null
    }
    const num = (v: unknown): number | null =>
        v === null || v === undefined || !Number.isFinite(Number(v)) ? null : Number(v)
    const series = parsed.map(({ f, cols, keys }) => {
        const data: (BoxPlotDatum | null)[] = labels.map(() => null)
        keys.forEach((k, i) => {
            const v = {
                min: num(cols.min!.values[i]),
                p25: num(cols.p25!.values[i]),
                median: num(cols.median!.values[i]),
                p75: num(cols.p75!.values[i]),
                max: num(cols.max!.values[i]),
            }
            if (Object.values(v).some((x) => x === null)) {
                return
            }
            data[at.get(k)!] = {
                ...(v as Record<string, number>),
                mean: num(cols.mean?.values[i]) ?? v.median!,
                day: k,
            } as BoxPlotDatum
        })
        return { label: f.name ?? 'value', data }
    })
    return { labels, series, hasMean }
}

export function BoxPlotViz({ frames, panel, options, timezone, onDrill }: VizProps<O>): React.JSX.Element {
    const theme = useDisplayChartTheme()
    const b = toBoxes(frames)
    if (!b || !b.labels.length) {
        return <EmptyData message="No data: a box plot needs min, p25, median, p75 and max columns" />
    }
    const time = b.labels.every((l) => /^\d{4}-\d\d-\d\dT/.test(l))
    const x = time ? xAxisFor(b.labels, timezone) : undefined
    const named = withOverrides(panel, b.series)
    const colors = colorize(
        panel,
        named.map((s) => ({ label: s.label, color: s.color, data: s.data.map((d) => d?.median ?? null) })),
        theme.colors
    )
    const series = named.map((s, i) => ({ ...s, color: colors[i]!.color }))
    return (
        <BoxPlot
            className="min-h-0 flex-1"
            theme={theme}
            labels={b.labels}
            series={series.map((s, i) => ({ key: String(i), label: s.label, color: s.color, data: s.data }))}
            onBoxClick={
                onDrill
                    ? (d) =>
                          onDrill({
                              refId: frames[0]?.refId,
                              series: { name: d.series.label },
                              value: d.datum.median,
                              ...(time ? { time: bucketOf(b.labels, d.dataIndex) } : { category: d.label }),
                          })
                    : undefined
            }
            config={
                {
                    ...(options.horizontal ? { axisOrientation: 'horizontal' } : {}),
                    meanRadius: b.hasMean ? 3 : 0,
                    showGrid: true,
                    ...(x ? { xTickFormatter: (l: string) => x.tickFormatter(l) } : {}),
                    yTickFormatter: (v: number) => tooltipFor(panel, panel.fieldConfig?.unit).valueFormatter(v),
                    legend: {
                        show: options.legend !== 'none' && series.length > 1,
                        position: options.legend === 'none' ? 'bottom' : options.legend,
                    },
                } as never
            }
        />
    )
}
