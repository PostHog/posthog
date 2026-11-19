import { IconCheck } from '@posthog/icons'
import { Textarea, cn } from '@posthog/quill'

import { CHART_TYPES, chartType } from '../charts/chartTypes'
import type { Panel as PanelSpec } from '../spec'
import { FieldRow, Section, Segmented, Toggle } from './OptionsForm'

const REDUCERS = [
    ['last', 'Last'],
    ['mean', 'Average'],
    ['min', 'Lowest'],
    ['max', 'Highest'],
    ['sum', 'Total'],
] as const

const TYPES_WITH_OPTIONS = new Set(['timeseries', 'stat', 'gauge', 'bar', 'pie', 'text'])

export function VizOptions({
    panel,
    onChange,
}: {
    panel: PanelSpec
    onChange: (viz: PanelSpec['viz']) => void
}): JSX.Element {
    const type = panel.viz?.type ?? ''
    const options: Record<string, unknown> = panel.viz?.options ?? {}
    const setOption = (key: string, value: unknown): void => {
        const { [key]: _previous, ...rest } = options
        onChange({ ...panel.viz, options: value === undefined ? rest : { ...rest, [key]: value } })
    }
    const bars = options.style === 'bars'

    return (
        <div className="flex flex-col gap-2">
            <Section title="Chart type">
                {type && !chartType(type) && (
                    <div className="text-xs text-muted-foreground">
                        "{type}" charts don't show on this page yet. Pick another chart type.
                    </div>
                )}
                <div
                    className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-2"
                    role="radiogroup"
                    aria-label="Chart type"
                >
                    {CHART_TYPES.map((candidate) => {
                        const selected = candidate.type === type
                        return (
                            <button
                                key={candidate.type}
                                type="button"
                                role="radio"
                                aria-checked={selected}
                                data-attr={`dashboard-v2-viz-${candidate.type}`}
                                onClick={() => !selected && onChange({ type: candidate.type })}
                                className={cn(
                                    'flex cursor-pointer flex-col gap-0.5 rounded-lg border p-2 text-left transition-colors motion-reduce:transition-none focus-visible:outline-2 focus-visible:outline-ring',
                                    selected ? 'border-ring bg-fill-selected ring-1 ring-ring' : 'hover:bg-fill-hover'
                                )}
                            >
                                <span className="flex items-center gap-1 text-xs font-medium">
                                    <span className="min-w-0 flex-1 truncate">{candidate.label}</span>
                                    {selected && <IconCheck className="size-3.5 shrink-0" />}
                                </span>
                                <span className="text-[11px] leading-snug text-muted-foreground">
                                    {candidate.description}
                                </span>
                            </button>
                        )
                    })}
                </div>
            </Section>
            {TYPES_WITH_OPTIONS.has(type) && (
                <Section title="Options">
                    {type === 'timeseries' && (
                        <>
                            <FieldRow label="Draw as">
                                <Segmented
                                    options={[
                                        ['line', 'Lines'],
                                        ['bars', 'Bars'],
                                    ]}
                                    value={bars ? 'bars' : 'line'}
                                    onChange={(style) => setOption('style', style === 'bars' ? 'bars' : undefined)}
                                />
                            </FieldRow>
                            {!bars && (
                                <Toggle
                                    label="Fill under the lines"
                                    hint="Shades the area between each line and the axis"
                                    checked={options.area === true}
                                    onChange={(area) => setOption('area', area || undefined)}
                                />
                            )}
                        </>
                    )}
                    {(type === 'stat' || type === 'gauge') && (
                        <FieldRow label="Value" description="The one number shown for each series over the time range">
                            <Segmented
                                options={REDUCERS}
                                value={typeof options.reduce === 'string' ? options.reduce : 'last'}
                                onChange={(reduce) => setOption('reduce', reduce === 'last' ? undefined : reduce)}
                            />
                        </FieldRow>
                    )}
                    {type === 'stat' && (
                        <Toggle
                            label="Trend line"
                            hint="Draws the series as a small line with the number"
                            checked={options.sparkline !== false}
                            onChange={(sparkline) => setOption('sparkline', sparkline ? undefined : false)}
                        />
                    )}
                    {type === 'bar' && (
                        <>
                            <Toggle
                                label="Funnel"
                                hint="Draws the bars as the steps of a funnel"
                                checked={options.funnel === true}
                                onChange={(funnel) => setOption('funnel', funnel || undefined)}
                            />
                            <Toggle
                                label="Horizontal bars"
                                hint="Bars run left to right, one row for each category"
                                checked={options.horizontal === true}
                                onChange={(horizontal) => setOption('horizontal', horizontal || undefined)}
                            />
                        </>
                    )}
                    {type === 'pie' && (
                        <Toggle
                            label="Donut"
                            hint="Leaves the middle of the pie empty"
                            checked={options.donut !== false}
                            onChange={(donut) => setOption('donut', donut ? undefined : false)}
                        />
                    )}
                    {type === 'text' && (
                        <FieldRow label="Text" description="Markdown: headings, lists and links" asLabel>
                            <Textarea
                                rows={10}
                                className="font-mono text-xs"
                                value={typeof options.markdown === 'string' ? options.markdown : ''}
                                onChange={(e) => setOption('markdown', e.target.value)}
                                data-attr="dashboard-v2-viz-markdown"
                            />
                        </FieldRow>
                    )}
                </Section>
            )}
        </div>
    )
}
