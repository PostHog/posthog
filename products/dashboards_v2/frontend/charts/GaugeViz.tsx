import { Gauge } from '@posthog/quill-charts'

import { useDisplayChartTheme } from '../editor/display'
import { colorToken, mapValue, reduceParts, thresholdColor } from './chartCommon'
import { colorize, schemeColor } from './colors'
import { EmptyData } from './EmptyData'
import { formatValue } from './format'
import type { GaugeOptions as O } from './options'
import type { VizProps } from './registry'

export function GaugeViz({ frames, panel, options, width, height }: VizProps<O>): React.JSX.Element {
    const theme = useDisplayChartTheme()
    const fc = panel.fieldConfig
    const parts = reduceParts(panel, frames, options.reduce)
    if (!parts.length) {
        return <EmptyData />
    }
    const unit = fc?.unit ?? parts[0]?.unit
    const min = fc?.min ?? 0
    const max =
        fc?.max ??
        (unit === '%' ? 100 : unit === 'percentunit' ? 1 : Math.max(...parts.map((p) => p.value ?? 0), min + 1))
    const own = colorize(
        panel,
        parts.map((p) => ({ label: p.name, data: [p.value], ...(p.color ? { color: p.color } : {}) })),
        theme.colors
    ).map((c, i) => (parts[i]!.color || panel.fieldConfig?.color?.mode === 'palette-classic' ? c.color : undefined))
    const base = (name: string, v: number | null): string =>
        own[parts.findIndex((p) => p.name === name)] ??
        mapValue(panel, v)?.color ??
        schemeColor(panel, name, [v], theme.colors) ??
        theme.colors[0]!
    if (options.shape === 'arc') {
        const steps = (fc?.thresholds ?? []).map((t) => ({ value: t.value, color: colorToken(t.color) }))
        const lowest = Math.min(...steps.map((t) => t.value))
        const cols = gaugeColumns(parts.length, width, height)
        return (
            <div
                className="grid h-full gap-2"
                style={{
                    gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
                    gridTemplateRows: `repeat(${Math.ceil(parts.length / cols)}, minmax(0, 1fr))`,
                }}
            >
                {parts.map((p, i) => {
                    const mapped = mapValue(panel, p.value)?.color
                    const thresholds =
                        !mapped && steps.length
                            ? lowest > min
                                ? [{ value: min, color: base(p.name, p.value) }, ...steps]
                                : steps
                            : undefined
                    return (
                        <Gauge
                            key={i}
                            className="h-full min-h-0 w-full min-w-0"
                            theme={theme}
                            value={p.value}
                            min={min}
                            max={max}
                            thresholds={thresholds}
                            color={base(p.name, p.value)}
                            label={options.showName && parts.length > 1 ? p.name : undefined}
                            config={{
                                valueFormatter: (v) =>
                                    mapValue(panel, v)?.text ?? formatValue(v, p.unit ?? unit, fc?.decimals),
                            }}
                        />
                    )
                })}
            </div>
        )
    }
    const vertical = options.orientation === 'vertical'
    return (
        <div
            className={`flex h-full gap-2 overflow-auto p-1 ${vertical ? 'flex-row items-end justify-around' : 'flex-col justify-center'}`}
        >
            {parts.map((p, i) => {
                const pct = p.value === null ? 0 : Math.max(0, Math.min(1, (p.value - min) / (max - min || 1)))
                const color =
                    own[i] ??
                    mapValue(panel, p.value)?.color ??
                    thresholdColor(p.value, panel) ??
                    schemeColor(panel, p.name, [p.value], theme.colors) ??
                    'var(--color-chart-1, #1d4aff)'
                const text = mapValue(panel, p.value)?.text ?? formatValue(p.value, unit, fc?.decimals)
                return vertical ? (
                    <div key={i} className="flex h-full min-w-0 flex-1 flex-col items-center gap-1">
                        <div className="text-sm font-semibold tabular-nums" style={{ color }}>
                            {text}
                        </div>
                        <div className="relative w-full max-w-10 flex-1 rounded bg-muted">
                            <div
                                className="absolute bottom-0 w-full rounded"
                                style={{ height: `${pct * 100}%`, background: color }}
                            />
                        </div>
                        {options.showName && parts.length > 1 && (
                            <div
                                className="w-full truncate text-center text-[10px] text-muted-foreground"
                                title={p.name}
                            >
                                {p.name}
                            </div>
                        )}
                    </div>
                ) : (
                    <div key={i} className="flex min-h-0 items-center gap-2">
                        {options.showName && parts.length > 1 && (
                            <div className="w-1/3 shrink-0 truncate text-xs text-muted-foreground" title={p.name}>
                                {p.name}
                            </div>
                        )}
                        <div className="relative h-4 min-w-0 flex-1 rounded bg-muted">
                            <div
                                className="absolute inset-y-0 left-0 rounded"
                                style={{ width: `${pct * 100}%`, background: color }}
                            />
                        </div>
                        <div className="w-20 shrink-0 text-right text-sm font-semibold tabular-nums" style={{ color }}>
                            {text}
                        </div>
                    </div>
                )
            })}
        </div>
    )
}

export function gaugeColumns(n: number, w: number, h: number): number {
    let best = 1,
        size = 0
    for (let c = 1; c <= n; c++) {
        const s = Math.min(w / c, (h / Math.ceil(n / c)) * 1.2)
        if (s > size) {
            size = s
            best = c
        }
    }
    return best
}
