import { memo, useMemo, useState } from 'react'

import { IconCheck, IconChevronDown } from '@posthog/icons'

import type { DataFrame } from '../charts/frame'
import { parseOptions, vizRegistry } from '../charts/registry'
import { useSampleFrames } from '../panel/DashboardV2SamplePanel'
import { useElementSize } from '../panel/useElementSize'
import type { Panel as PanelSpec } from '../spec'
import { COLORED, ColorScheme } from './ColorScheme'
import { OptionsForm } from './OptionsForm'

type VizOptionValues = Record<string, unknown>
interface VizInfo {
    description: string
    initial?: VizOptionValues
    styles?: { name: string; options: VizOptionValues }[]
}

const VIZ_INFO: Record<string, VizInfo> = {
    timeseries: {
        description: 'Values over time as lines, areas, bars or points',
        styles: [
            { name: 'Lines', options: { style: 'line', area: false, stack: false, points: false } },
            { name: 'Area', options: { style: 'line', area: true, stack: false, points: false, gradient: false } },
            {
                name: 'Gradient area',
                options: { style: 'line', area: true, stack: false, points: false, gradient: true },
            },
            {
                name: 'Stacked area',
                options: { style: 'line', area: true, stack: true, percent: false, points: false },
            },
            {
                name: '100% stacked area',
                options: { style: 'line', area: true, stack: true, percent: true, points: false },
            },
            { name: 'Bars', options: { style: 'bars', area: false, stack: false, points: false } },
            {
                name: 'Stacked bars',
                options: { style: 'bars', area: false, stack: true, percent: false, points: false },
            },
            {
                name: '100% stacked bars',
                options: { style: 'bars', area: false, stack: true, percent: true, points: false },
            },
            { name: 'Points', options: { style: 'points', area: false, stack: false, points: false } },
        ],
    },
    bar: {
        description: 'Compare categories or buckets side by side',
        styles: [
            { name: 'Columns', options: { horizontal: false, stack: false, funnel: false } },
            { name: 'Stacked columns', options: { horizontal: false, stack: true, funnel: false } },
            { name: 'Bars', options: { horizontal: true, stack: false, funnel: false } },
            { name: 'Stacked bars', options: { horizontal: true, stack: true, funnel: false } },
            { name: 'Funnel', options: { horizontal: false, stack: false, funnel: true } },
            { name: 'Horizontal funnel', options: { horizontal: true, stack: false, funnel: true } },
        ],
    },
    pie: {
        description: 'Parts of a whole',
        styles: [
            { name: 'Donut', options: { donut: true, legend: 'right' } },
            { name: 'Pie', options: { donut: false, legend: 'right' } },
            { name: 'Donut, legend below', options: { donut: true, legend: 'bottom' } },
            { name: 'Chart only', options: { donut: true, legend: 'none' } },
        ],
    },
    stat: {
        description: 'One big number per series, with an optional sparkline',
        styles: [
            { name: 'Value', options: { colorMode: 'value', sparkline: false } },
            { name: 'Value + sparkline', options: { colorMode: 'value', sparkline: true, sparklineFill: true } },
            { name: 'Background', options: { colorMode: 'background', sparkline: false } },
            {
                name: 'Background + sparkline',
                options: { colorMode: 'background', sparkline: true, sparklineFill: true },
            },
            { name: 'Solid + line', options: { colorMode: 'background_solid', sparkline: true, sparklineFill: false } },
            { name: 'Plain + sparkline', options: { colorMode: 'none', sparkline: true, sparklineFill: true } },
        ],
    },
    gauge: {
        description: 'A value against its min and max',
        initial: { shape: 'arc' },
        styles: [
            { name: 'Radial', options: { shape: 'arc', showName: true } },
            { name: 'Horizontal bars', options: { shape: 'bars', orientation: 'horizontal', showName: true } },
            { name: 'Vertical bars', options: { shape: 'bars', orientation: 'vertical', showName: true } },
            { name: 'Bars only', options: { shape: 'bars', orientation: 'horizontal', showName: false } },
        ],
    },
    table: {
        description: 'Rows and columns you can sort',
        styles: [
            { name: 'Table', options: { showHeader: true, footer: undefined } },
            { name: 'With totals', options: { showHeader: true, footer: 'sum' } },
            { name: 'No header', options: { showHeader: false, footer: undefined } },
        ],
    },
    retention: {
        description: 'Cohorts down, periods across, with the share of each cohort still active',
        styles: [
            { name: 'With mean', options: { display: 'table', mean: true, showSize: true } },
            { name: 'Cohorts only', options: { display: 'table', mean: false, showSize: true } },
            { name: 'Compact', options: { display: 'table', mean: false, showSize: false } },
            { name: 'Curves', options: { display: 'curve', mean: true } },
        ],
    },
    boxplot: {
        description: 'A distribution per day or category, with quartiles, whiskers and the median',
        styles: [
            { name: 'Columns', options: { horizontal: false } },
            { name: 'Rows', options: { horizontal: true } },
        ],
    },
    sankey: {
        description: 'Paths between steps or states as ribbons',
        styles: [
            { name: 'Flows', options: { showValues: false } },
            { name: 'With values', options: { showValues: true } },
        ],
    },
    flamegraph: { description: 'Where time or cost goes, as nested blocks' },
    heatmap: {
        description: 'A distribution over time, or a grid of two categories',
        styles: [
            { name: 'Log colors', options: { colorScale: 'log', showValues: false } },
            { name: 'Linear colors', options: { colorScale: 'linear', showValues: false } },
            { name: 'Linear with values', options: { colorScale: 'linear', showValues: true } },
        ],
    },
    logs: {
        description: 'Log lines with a volume histogram',
        styles: [
            { name: 'Volume + lines', options: { histogram: true, wrap: false } },
            { name: 'Lines', options: { histogram: false, wrap: false } },
            { name: 'Wrapped', options: { histogram: true, wrap: true } },
        ],
    },
    traces: {
        description: 'Traces or spans with a volume histogram, or one trace as a waterfall of its spans',
        styles: [
            { name: 'Volume + list', options: { histogram: true } },
            { name: 'List', options: { histogram: false } },
        ],
    },
    text: { description: 'Markdown notes, links and headings' },
}

const NO_OPTIONS: VizOptionValues = {}
const TEXT_SAMPLE: VizOptionValues = {
    markdown: '### Notes\n\nWrite **markdown**: headings, lists and [links](https://posthog.com).',
}
const thumbDefaults = (type: string): VizOptionValues =>
    type === 'text' ? TEXT_SAMPLE : (VIZ_INFO[type]?.initial ?? NO_OPTIONS)

function activeStyle(type: string, options: VizOptionValues): string | undefined {
    return VIZ_INFO[type]?.styles?.find((style) =>
        Object.entries(style.options).every(([key, value]) => options[key] === value)
    )?.name
}

export function VizOptions({
    panel,
    frames,
    onChange,
    onFieldConfig,
}: {
    panel: PanelSpec
    frames: DataFrame[]
    onChange: (viz: PanelSpec['viz']) => void
    onFieldConfig: (fc: PanelSpec['fieldConfig']) => void
}): JSX.Element {
    const type = panel.viz?.type ?? ''
    const def = vizRegistry[type]
    const info = VIZ_INFO[type]
    const [picking, setPicking] = useState(!def)
    const shown = useMemo(
        () => ({ title: panel.title, viz: panel.viz, fieldConfig: panel.fieldConfig, transforms: panel.transforms }),
        [panel.title, panel.viz, panel.fieldConfig, panel.transforms]
    )
    const current = useMemo(() => (def ? parseOptions(def, panel.viz.options).options : {}), [def, panel.viz?.options])
    const active = def ? activeStyle(type, current) : undefined
    const setOptions = (o: VizOptionValues): void =>
        onChange({ ...panel.viz, options: Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined)) })

    return (
        <div className="flex flex-col gap-3">
            <div className="overflow-hidden rounded-lg border bg-card">
                <div
                    {...pressable(() => setPicking((p) => !p))}
                    className="flex w-full cursor-pointer items-center gap-3 p-2 text-left hover:bg-fill-hover"
                    aria-expanded={picking}
                    data-attr="dashboard-v2-viz-type"
                >
                    {def && (
                        <div className="w-24 shrink-0">
                            <VizThumb type={type} panel={shown} options={current} frames={frames} />
                        </div>
                    )}
                    <div className="min-w-0 flex-1">
                        <div className="text-[11px] text-muted-foreground">Chart type</div>
                        <div className="text-sm font-semibold">{def?.label ?? `Unknown chart type "${type}"`}</div>
                        {info && <div className="truncate text-xs text-muted-foreground">{info.description}</div>}
                    </div>
                    <IconChevronDown
                        className={`size-4 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none ${picking ? 'rotate-180' : ''}`}
                    />
                </div>
                {picking && (
                    <div className="grid grid-cols-[repeat(auto-fill,minmax(132px,1fr))] gap-2 border-t p-2">
                        {Object.entries(vizRegistry).map(([key, v]) => (
                            <Tile
                                key={key}
                                selected={key === type}
                                label={v.label}
                                title={VIZ_INFO[key]?.description}
                                onClick={() => {
                                    if (key !== type) {
                                        onChange({ type: key, options: { ...VIZ_INFO[key]?.initial } })
                                    }
                                    setPicking(false)
                                }}
                                dataAttr={`dashboard-v2-viz-${key}`}
                            >
                                {key === type ? (
                                    <VizThumb type={key} panel={shown} options={current} frames={frames} />
                                ) : (
                                    <SampleThumb type={key} panel={shown} options={thumbDefaults(key)} />
                                )}
                            </Tile>
                        ))}
                    </div>
                )}
            </div>
            {info?.styles && (
                <div className="rounded-lg border bg-card">
                    <div className="flex items-center gap-2 px-3 py-2">
                        <div className="text-sm font-semibold">Panel styles</div>
                        {!active && <span className="text-[11px] text-muted-foreground">Custom</span>}
                    </div>
                    <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-2 border-t p-2">
                        {info.styles.map((s) => (
                            <Tile
                                key={s.name}
                                selected={s.name === active}
                                label={s.name}
                                onClick={() => setOptions({ ...current, ...s.options })}
                                dataAttr={`dashboard-v2-style-${s.name}`}
                            >
                                <StyleThumb
                                    type={type}
                                    panel={shown}
                                    current={current}
                                    style={s.options}
                                    frames={frames}
                                />
                            </Tile>
                        ))}
                    </div>
                </div>
            )}
            {COLORED.has(type) && <ColorScheme panel={panel} frames={frames} onChange={onFieldConfig} />}
            {def && <OptionsForm schema={def.options} value={current} onChange={setOptions} />}
        </div>
    )
}

function Tile({
    selected,
    label,
    title,
    onClick,
    dataAttr,
    children,
}: {
    selected: boolean
    label: string
    title?: string
    onClick: () => void
    dataAttr?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div
            {...pressable(onClick)}
            title={title}
            data-attr={dataAttr}
            aria-pressed={selected}
            className={`relative flex cursor-pointer flex-col gap-1.5 rounded-lg border p-1.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-ring ${selected ? 'border-ring bg-fill-selected ring-1 ring-ring' : 'hover:bg-fill-hover'}`}
        >
            {children}
            <div className="flex items-center gap-1 px-0.5 text-xs font-medium">
                <span className="min-w-0 flex-1 truncate">{label}</span>
                {selected && <IconCheck className="size-3.5 shrink-0" />}
            </div>
        </div>
    )
}

const pressable = (
    onClick: () => void
): { role: string; tabIndex: number; onClick: () => void; onKeyDown: (e: React.KeyboardEvent) => void } => ({
    role: 'button',
    tabIndex: 0,
    onClick,
    onKeyDown: (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onClick()
        }
    },
})

function StyleThumb({
    type,
    panel,
    current,
    style,
    frames,
}: {
    type: string
    panel: PanelSpec
    current: VizOptionValues
    style: VizOptionValues
    frames: DataFrame[]
}): JSX.Element {
    const options = useMemo(() => ({ ...current, ...style }), [current, style])
    return <VizThumb type={type} panel={panel} options={options} frames={frames} legend={'legend' in style} />
}

function SampleThumb({
    type,
    panel,
    options,
}: {
    type: string
    panel: PanelSpec
    options: VizOptionValues
}): JSX.Element {
    const typed = useMemo(() => ({ ...panel, viz: { type, options } }), [panel, type, options])
    const frames = useSampleFrames('thumbnail', typed)
    return <VizThumb type={type} panel={panel} options={options} frames={frames} />
}

const W = 260
const H = 160
const PANEL_CARD =
    'relative isolate flex flex-col rounded-md border bg-card has-[[data-panel-bg]]:border-transparent has-[[data-panel-bg]]:text-white'

export const VizThumb = memo(function VizThumb({
    type,
    panel,
    options,
    frames,
    legend,
}: {
    type: string
    panel: PanelSpec
    options: VizOptionValues
    frames: DataFrame[]
    legend?: boolean
}): JSX.Element {
    const def = vizRegistry[type]!
    const { ref, width } = useElementSize<HTMLDivElement>()
    const opts = useMemo(
        () => parseOptions(def, { ...options, legend: (options.legend && legend) || 'none' }).options,
        [def, options, legend]
    )
    const Viz = def.component
    return (
        <div
            ref={ref}
            {...{ inert: '' }}
            aria-hidden
            className="pointer-events-none relative w-full overflow-hidden rounded-md"
            style={{ aspectRatio: `${W} / ${H}` }}
        >
            {width > 0 && (
                <div
                    className={`${PANEL_CARD} absolute left-0 top-0 origin-top-left`}
                    style={{ width: W, height: H, transform: `scale(${width / W})` }}
                >
                    <div className="flex h-8 shrink-0 items-center truncate px-2 text-xs font-medium">
                        {panel.title || def.label}
                    </div>
                    <div className="min-h-0 flex-1 px-2 pb-2">
                        <div className="flex flex-col" style={{ width: W - 18, height: H - 42 }}>
                            <Viz
                                frames={type === 'text' ? [] : frames}
                                panel={{ ...panel, viz: { type, options: opts } }}
                                options={opts}
                                width={W - 18}
                                height={H - 42}
                            />
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
})
