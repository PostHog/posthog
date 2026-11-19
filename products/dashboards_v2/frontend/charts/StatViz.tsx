import type { CSSProperties } from 'react'

import { IconArrowRightDown, IconArrowUpRight, IconTriangleDownFilled, IconTriangleUpFilled } from '@posthog/icons'
import { MetricCard } from '@posthog/quill-charts'

import { useDisplayChartTheme } from '../editor/display'
import { colorToken, mapValue, panelBackground, reduceParts, thresholdColor, xAxisFor } from './chartCommon'
import { schemeColor } from './colors'
import { EmptyData } from './EmptyData'
import { formatValue } from './format'
import { reduce, toXSeries, hasTime, reduceFrame, drawnIncomplete } from './frames'
import type { StatOptions as O } from './options'
import type { VizProps } from './registry'

export function changeFrom(value: number | null, before: number | null): { value: number } | null {
    return value !== null && before !== null && Number.isFinite(before) && before !== 0
        ? { value: ((value - before) / Math.abs(before)) * 100 }
        : null
}

function Change({ value, size }: { value: number | null; size: number }): React.JSX.Element {
    if (value === null || !Number.isFinite(value)) {
        return (
            <div className="text-muted-foreground" style={{ fontSize: size }}>
                No data for the previous period
            </div>
        )
    }
    const Icon = value < 0 ? IconArrowRightDown : IconArrowUpRight
    return (
        <div className="flex items-center gap-1.5 whitespace-nowrap text-muted-foreground" style={{ fontSize: size }}>
            <Icon className="shrink-0" style={{ width: size * 1.2, height: size * 1.2 }} />
            {value === 0
                ? 'No change'
                : `${value < 0 ? 'Down' : 'Up'} ${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`}{' '}
            from previous period
        </div>
    )
}

function ChangeBadge({ value, good }: { value: number | null; good: 'up' | 'down' }): React.JSX.Element {
    const known = value !== null && Number.isFinite(value)
    const tone = !known || value === 0 ? 'muted' : value > 0 === (good === 'up') ? 'good' : 'bad'
    const Icon = known && value! < 0 ? IconTriangleDownFilled : IconTriangleUpFilled
    return (
        <span
            data-testid="stat-change-badge"
            className={`pointer-events-none absolute top-1.5 right-2 flex items-center gap-0.5 rounded-full px-2 py-0.5 text-xs font-medium tabular-nums transition-opacity group-hover:opacity-0 ${
                tone === 'good'
                    ? 'bg-muted text-success-foreground'
                    : tone === 'bad'
                      ? 'bg-muted text-destructive-foreground'
                      : 'bg-muted text-muted-foreground'
            }`}
        >
            {known ? (
                <>
                    {value !== 0 && <Icon className="size-3" />}
                    {`${value! > 0 ? '+' : ''}${value!.toFixed(1)}%`}
                </>
            ) : (
                'no data before'
            )}
        </span>
    )
}

export function StatViz({
    frames: all,
    panel,
    options,
    height,
    width,
    timezone,
    onDrill,
}: VizProps<O>): React.JSX.Element {
    const theme = useDisplayChartTheme()
    const keep = (name: string): boolean => name === options.field || name === `${options.field} (previous)`
    const frames = options.field
        ? all.map((f) => ({ ...f, fields: f.fields.filter((x) => x.type !== 'number' || keep(x.name)) }))
        : all
    if (!frames.length) {
        return <EmptyData />
    }
    const unit = panel.fieldConfig?.unit ?? frames[0]?.fields.find((f) => f.type === 'number')?.config?.unit
    const fmt = (v: number | null): string =>
        mapValue(panel, v)?.text ?? formatValue(v, unit, panel.fieldConfig?.decimals)
    const groups = new Map<string, typeof frames>()
    for (const f of frames) {
        if (!options.compareTo || f.refId !== options.compareTo) {
            groups.set(f.refId ?? '', [...(groups.get(f.refId ?? '') ?? []), f])
        }
    }
    const partsOf = (
        fs: typeof frames
    ): {
        name: string
        value: number | null
        data: number[]
        labels: string[]
        categorical: boolean
        unit: string | undefined
        color: string | undefined
    }[] => reduceParts(panel, fs, options.reduce)
    const parts = [...groups.values()].flatMap((fs) => {
        const before = partsOf(fs.filter((f) => f.meta?.previous))
        return partsOf(fs.filter((f) => !f.meta?.previous)).map((p, i) => ({
            ...p,
            change: before.length ? changeFrom(p.value, before[i]?.value ?? null) : undefined,
            prev: before.length ? (before[i]?.value ?? null) : undefined,
        }))
    })
    if (!parts.length) {
        return <EmptyData />
    }
    const primary = parts[0]!
    const partial = primary.categorical
        ? -1
        : drawnIncomplete(
              panel,
              frames,
              primary.labels.map((l) => new Date(l).getTime())
          )
    const drillOn = (p: (typeof parts)[number]): { onClick: () => void } | { onClick?: undefined } =>
        onDrill
            ? {
                  onClick: () =>
                      onDrill({
                          refId: frames.find((f) => !f.meta?.previous)?.refId,
                          series: { name: p.name },
                          value: p.value,
                      }),
              }
            : {}
    const before = options.compareTo ? frames.filter((f) => f.refId === options.compareTo) : []
    const prev = before.length
        ? hasTime(before)
            ? reduce(toXSeries(before).series[0]?.data ?? [], options.reduce)
            : reduceFrame(before[0]!, options.reduce)
        : null
    const change = options.compareTo ? changeFrom(primary.value, prev) : primary.change
    const pill = change === undefined ? undefined : { value: change?.value ?? null }
    const fill = options.colorMode === 'background' || options.colorMode === 'background_solid'
    const colorOf = (p: (typeof parts)[number]): string | undefined =>
        options.colorMode === 'none'
            ? undefined
            : (mapValue(panel, p.value)?.color ??
              thresholdColor(p.value, panel) ??
              schemeColor(panel, p.name, p.data.length ? p.data : [p.value], theme.colors) ??
              (fill ? colorToken('blue') : undefined))
    const color = colorOf(primary)
    const showSpark = options.sparkline && primary.data.length > 1 && height > 70
    const mode = options.textMode
    if (parts.length > 1) {
        const n = parts.length,
            gap = 4,
            named = mode !== 'value'
        const chars = Math.max(3, ...parts.map((p) => fmt(p.value).length))
        const fit = (cols: number): { cols: number; inline: boolean; font: number } => {
            const rows = Math.ceil(n / cols)
            const w = (width - gap * (cols - 1)) / cols,
                h = (height - gap * (rows - 1)) / rows
            const inline = named && w > h * 4
            const font = Math.min(
                options.valueSize ?? 120,
                h * (inline || !named ? 0.6 : 0.42),
                ((inline ? w * 0.55 : w) - 24) / (chars * 0.62)
            )
            return { cols, inline, font: Math.max(10, Math.floor(font)) }
        }
        const tries =
            options.orientation === 'horizontal'
                ? [1]
                : options.orientation === 'vertical'
                  ? [n]
                  : Array.from({ length: n }, (_, k) => k + 1)
        const best = tries.map(fit).reduce((a, b) => (b.font > a.font ? b : a))
        const nameSize = Math.min(22, Math.max(11, Math.round(best.font * 0.38)))
        return (
            <div
                className="grid h-full overflow-hidden"
                style={{
                    gridTemplateColumns: `repeat(${best.cols}, minmax(0, 1fr))`,
                    gridAutoRows: 'minmax(0, 1fr)',
                    gap,
                }}
            >
                {parts.map((p, i) => {
                    const c = colorOf(p)
                    const tile =
                        fill && c
                            ? {
                                  background: panelBackground(c, options.colorMode === 'background_solid'),
                                  color: '#fff',
                              }
                            : undefined
                    return (
                        <div
                            key={i}
                            {...drillOn(p)}
                            className={`flex min-w-0 overflow-hidden rounded px-3 ${best.inline ? 'items-center justify-between gap-3' : `flex-col justify-center gap-1 ${named ? '' : 'items-center'}`}`}
                            style={tile}
                        >
                            {named && (
                                <div
                                    className={`truncate leading-tight ${tile ? 'opacity-90' : 'text-muted-foreground'}`}
                                    style={{ fontSize: nameSize }}
                                    title={p.name}
                                >
                                    {p.name}
                                </div>
                            )}
                            {mode !== 'name' && (
                                <div
                                    className="whitespace-nowrap font-semibold leading-none tracking-tight tabular-nums"
                                    style={{ fontSize: best.font, color: tile ? undefined : c }}
                                >
                                    {fmt(p.value)}
                                </div>
                            )}
                            {p.change !== undefined && !best.inline && (
                                <Change value={p.change?.value ?? null} size={nameSize} />
                            )}
                        </div>
                    )
                })}
            </div>
        )
    }
    const sparkHeight = Math.max(16, Math.min(60, height - 70))
    const chars = Math.max(3, fmt(primary.value).length)
    const size = Math.round(
        Math.max(
            20,
            Math.min(
                options.valueSize ?? 120,
                (height - (showSpark ? sparkHeight : 0) - 28) * 0.8,
                (width - 24) / (chars * 0.62)
            )
        )
    )
    const bg =
        fill && color ? (
            <div
                data-panel-bg
                aria-hidden
                className="absolute inset-0 -z-10 rounded-md"
                style={{ background: panelBackground(color, options.colorMode === 'background_solid') }}
            />
        ) : null
    const text = bg ? '#fff' : color
    const small = Math.max(12, Math.min(16, Math.round(size / 4)))
    if (!showSpark) {
        const badge = options.change === 'badge' && pill
        const before = options.compareTo ? prev : primary.prev
        return (
            <div
                {...drillOn(primary)}
                className={`flex h-full flex-col justify-center overflow-hidden ${badge ? 'items-start gap-1.5 px-1' : 'items-center gap-3'}`}
            >
                {bg}
                <div
                    className="whitespace-nowrap font-bold leading-none tracking-tight tabular-nums"
                    style={{ fontSize: size, color: text }}
                >
                    {fmt(primary.value)}
                </div>
                {badge ? (
                    <>
                        <ChangeBadge value={pill.value} good={options.goodDirection} />
                        {before !== undefined && (
                            <div className="whitespace-nowrap text-muted-foreground" style={{ fontSize: small }}>
                                vs. {before === null ? 'no data' : fmt(before)} prior
                            </div>
                        )}
                    </>
                ) : (
                    pill && <Change value={pill.value} size={small} />
                )}
            </div>
        )
    }
    return (
        <div
            {...drillOn(primary)}
            className="h-full"
            style={{ ...(text ? { '--stat-color': text } : {}), '--stat-size': `${size}px` } as CSSProperties}
        >
            {bg}
            <MetricCard
                className="h-full border-0 shadow-none bg-transparent"
                title=""
                value={primary.value ?? undefined}
                data={primary.data.map((v) => (Number.isNaN(v) ? 0 : v))}
                labels={primary.labels}
                theme={theme}
                color={bg ? 'rgba(255,255,255,0.9)' : color}
                formatValue={(v) => fmt(v)}
                showChange={!!options.showChange || !!pill}
                {...(pill
                    ? {
                          change,
                          changeTooltip: options.compareTo
                              ? `vs the previous period: ${prev === null ? 'no data' : fmt(prev)}`
                              : 'vs the previous period',
                      }
                    : {})}
                goodDirection={options.goodDirection}
                changeInline
                hoverChangeFromPreviousPoint
                sparklineFill={options.sparklineFill !== false}
                sparklineFillOpacity={bg ? 0.3 : undefined}
                restingSubtitle=""
                formatLabel={primary.categorical ? (l) => l : xAxisFor(primary.labels, timezone).labelFormatter}
                sparklineHeight={sparkHeight}
                {...(partial >= 0 ? { sparklineDashedFromIndex: partial } : {})}
                headlineClassName={`[font-size:var(--stat-size)] leading-none${text ? ' [color:var(--stat-color)]' : ''}`}
            />
        </div>
    )
}
