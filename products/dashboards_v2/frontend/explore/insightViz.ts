import type { FieldConfig, Panel } from '../spec'

const BIG_NUMBER = 64

export function vizFor(node: any): Panel['viz'] {
    const source = node?.source ?? node
    switch (source?.kind) {
        case 'TrendsQuery': {
            const d = source.trendsFilter?.display ?? 'ActionsLineGraph'
            if (d === 'BoldNumber' || d === 'Metric') {
                return { type: 'stat', options: { sparkline: false, valueSize: BIG_NUMBER } }
            }
            if (d === 'ActionsPie') {
                return { type: 'pie' }
            }
            const tf = source.trendsFilter ?? {}
            const values = {
                ...(tf.showValuesOnSeries ? { showValues: true } : {}),
                ...(tf.showMovingAverage ? { movingAverage: Number(tf.movingAverageIntervals) || 7 } : {}),
                ...(tf.showTrendLines ? { trendLine: 'linear' } : {}),
                ...(tf.showConfidenceIntervals ? { confidence: Number(tf.confidenceLevel) || 95 } : {}),
            }
            if (d === 'ActionsBarValue') {
                return { type: 'bar', options: { horizontal: true, colorBars: true, ...values } }
            }
            if (d === 'WorldMap') {
                return { type: 'geomap' }
            }
            if (d === 'ActionsTable') {
                return { type: 'table' }
            }
            if (d === 'BoxPlot') {
                return { type: 'boxplot' }
            }
            const percent = tf.showPercentStackView ? { stack: true, percent: true } : {}
            if (d === 'ActionsAreaGraph') {
                return { type: 'timeseries', options: { area: true, stack: true, ...percent, ...values } }
            }
            if (d === 'ActionsBar' || d === 'ActionsStackedBar') {
                return { type: 'timeseries', options: { style: 'bars', stack: true, ...percent, ...values } }
            }
            if (d === 'ActionsUnstackedBar') {
                return { type: 'timeseries', options: { style: 'bars', ...percent, ...values } }
            }
            const opts = { ...percent, ...values }
            return Object.keys(opts).length ? { type: 'timeseries', options: opts } : { type: 'timeseries' }
        }
        case 'LifecycleQuery':
            return { type: 'timeseries', options: { style: 'bars', stack: true } }
        case 'StickinessQuery':
            return { type: 'bar' }
        case 'FunnelsQuery': {
            const v = source.funnelsFilter?.funnelVizType ?? 'steps'
            if (v === 'trends') {
                return { type: 'timeseries' }
            }
            if (v !== 'steps') {
                return { type: 'bar' }
            }
            return {
                type: 'bar',
                options: {
                    funnel: true,
                    ...(source.funnelsFilter?.layout === 'horizontal' ? { horizontal: true } : {}),
                    ...(source.funnelsFilter?.funnelStepReference === 'previous' ? { stepReference: 'previous' } : {}),
                },
            }
        }
        case 'RetentionQuery': {
            const rf = source.retentionFilter ?? {}
            const options = {
                ...(rf.display === 'ActionsLineGraph' ? { display: 'curve' } : {}),
                ...(rf.meanRetentionCalculation === 'weighted' ? { meanBy: 'weighted' } : {}),
            }
            return Object.keys(options).length ? { type: 'retention', options } : { type: 'retention' }
        }
        case 'PathsQuery':
            return { type: 'sankey' }
        case 'MetricsQuery':
            return { type: 'timeseries' }
        default:
            return { type: 'table' }
    }
}

export function trendsDisplay(viz?: Panel['viz']): string {
    const o = (viz?.options ?? {}) as Record<string, unknown>
    switch (viz?.type) {
        case 'stat':
        case 'gauge':
            return 'BoldNumber'
        case 'pie':
            return 'ActionsPie'
        case 'boxplot':
            return 'BoxPlot'
        case 'table':
            return 'ActionsTable'
        case 'geomap':
            return 'WorldMap'
        case 'bar':
            return 'ActionsBarValue'
        case 'timeseries':
            return o.style === 'bars'
                ? o.stack
                    ? 'ActionsBar'
                    : 'ActionsUnstackedBar'
                : o.area
                  ? 'ActionsAreaGraph'
                  : 'ActionsLineGraph'
        default:
            return 'ActionsLineGraph'
    }
}

export function unitFor(
    f?: { style?: string | null; prefix?: string | null; suffix?: string | null; decimalPlaces?: number | null } | null
): { unit?: string; decimals?: number } {
    if (!f) {
        return {}
    }
    const unit =
        f.style === 'percent'
            ? 'percentunit'
            : f.style === 'short'
              ? f.prefix === '$'
                  ? 'currencyUSD'
                  : 'short'
              : (affixUnit(f.prefix, f.suffix) ?? (f.style === 'number' ? 'locale' : undefined))
    const decimals =
        typeof f.decimalPlaces === 'number' ? Math.max(0, Math.min(10, Math.round(f.decimalPlaces))) : undefined
    return { ...(unit ? { unit } : {}), ...(decimals !== undefined ? { decimals } : {}) }
}

const affixUnit = (pre?: string | null, suf?: string | null): string | undefined =>
    pre ? `prefix:${pre}${suf ? `|suffix:${suf}` : ''}` : suf ? `suffix:${suf}` : undefined

const UNITS: Record<string, string> = {
    percentage: '%',
    percentage_scaled: 'percentunit',
    duration: 's',
    duration_ms: 'ms',
    currency: 'currencyUSD',
}
export function fieldConfigFor(node: any): FieldConfig | undefined {
    const src = node?.source ?? node
    const tf = src?.trendsFilter
    const big = tf?.display === 'BoldNumber' || tf?.display === 'Metric'
    const unit =
        UNITS[tf?.aggregationAxisFormat ?? ''] ??
        affixUnit(tf?.aggregationAxisPrefix, tf?.aggregationAxisPostfix) ??
        (big ? 'locale' : undefined)
    const decimals = tf?.decimalPlaces
    const thresholds = big ? undefined : goalThresholds(tf?.goalLines)
    const overrides = seriesOverrides(src)
    const fc: FieldConfig = {
        ...(unit ? { unit } : {}),
        ...(decimals !== undefined && decimals !== null ? { decimals } : {}),
        ...(thresholds ? { thresholds } : {}),
        ...(overrides ? { overrides } : {}),
    }
    return Object.keys(fc).length ? fc : undefined
}

const PH_COLORS = [
    '#1d4aff',
    '#621da6',
    '#42827e',
    '#ce0e74',
    '#f14f58',
    '#7c440e',
    '#529a0a',
    '#0476fb',
    '#fe729e',
    '#35416b',
    '#41cbc4',
    '#b64b02',
    '#e4a604',
    '#a56eff',
    '#30d5c8',
]
const presetColor = (c: unknown): string | undefined => {
    if (typeof c !== 'string' || !c) {
        return undefined
    }
    const m = /^preset-(\d+)$/.exec(c)
    return m ? PH_COLORS[(Number(m[1]) - 1) % PH_COLORS.length] : c
}
const LIFECYCLE: Record<string, string> = {
    new: '#529a0a',
    returning: '#1d4aff',
    resurrecting: '#a56eff',
    dormant: '#f14f58',
}
const GOAL_COLOR = 'gray'

export function goalThresholds(lines: unknown): FieldConfig['thresholds'] {
    if (!Array.isArray(lines)) {
        return undefined
    }
    const out = lines
        .filter((l) => Number.isFinite(l?.value))
        .map((l) => ({
            value: Number(l.value),
            color: presetColor(l.borderColor) ?? GOAL_COLOR,
            ...(l.label && l.displayLabel !== false ? { label: String(l.label) } : {}),
        }))
    return out.length ? out : undefined
}

const BREAKDOWN_NAMES: Record<string, string> = {
    $$_posthog_breakdown_null_$$: 'None',
    $$_posthog_breakdown_other_$$: 'Other',
}
function trendsSeriesName(src: any, i: number, breakdown?: unknown): string {
    const s = src.series?.[i] ?? {}
    const base = s.custom_name || s.name || s.event || 'Series'
    if (breakdown === undefined || breakdown === null) {
        return base
    }
    const bd = [breakdown]
        .flat()
        .map((x) => BREAKDOWN_NAMES[String(x)] ?? String(x))
        .join(', ')
    return (src.series?.length ?? 0) > 1 ? `${base} - ${bd}` : bd
}

export function seriesOverrides(src: any): FieldConfig['overrides'] {
    const out: NonNullable<FieldConfig['overrides']> = {}
    const add = (name: string, o: Record<string, unknown>): void => {
        out[name] = { ...out[name], ...o }
    }
    if (src?.kind === 'LifecycleQuery') {
        for (const [k, color] of Object.entries(LIFECYCLE)) {
            add(k, { color })
        }
    }
    const tf = src?.trendsFilter ?? {}
    const formula = tf.formula || tf.formulas?.length || tf.formulaNodes?.length
    const bd = src?.breakdownFilter?.breakdown || src?.breakdownFilter?.breakdowns?.length
    const result = (i: number): string => (formula || bd ? `#${i}` : trendsSeriesName(src, i))
    if (src?.kind === 'TrendsQuery') {
        for (const [key, c] of Object.entries<any>(tf.resultCustomizations ?? {})) {
            let name: string | undefined
            if ((c?.assignmentBy ?? tf.resultCustomizationBy ?? 'value') === 'position') {
                name = /^\d+$/.test(key) ? result(Number(key)) : undefined
            } else if (!formula) {
                try {
                    const k = JSON.parse(key)
                    name = Number.isInteger(k?.series) ? trendsSeriesName(src, k.series, k.breakdown_value) : undefined
                } catch {
                    name = undefined
                }
            }
            if (!name) {
                continue
            }
            add(name, {
                ...(presetColor(c?.color) ? { color: presetColor(c.color) } : {}),
                ...(c?.hidden ? { hidden: true } : {}),
            })
        }
        for (const i of tf.hiddenLegendIndexes ?? []) {
            if (Number.isInteger(i)) {
                add(result(i), { hidden: true })
            }
        }
        if (tf.showMultipleYAxes && !bd) {
            const n = formula ? (tf.formulaNodes?.length ?? tf.formulas?.length ?? 1) : (src.series?.length ?? 0)
            for (let i = 1; i < n; i++) {
                add(result(i), { axis: 'right' })
            }
        }
    }
    for (const k of Object.keys(out)) {
        if (!Object.keys(out[k]!).length) {
            delete out[k]
        }
    }
    return Object.keys(out).length ? out : undefined
}
