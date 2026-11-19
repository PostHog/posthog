import { useMemo } from 'react'

import { IconCheck } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { useChartTheme } from 'lib/charts/hooks'

import { colorToken, withOverrides } from '../charts/chartCommon'
import { SCHEMES, along, byValue, colorize, defaultMode, schemeOf, type Scheme } from '../charts/colors'
import type { DataFrame } from '../charts/frame'
import { toCategories, toTable, toXSeries } from '../charts/frames'
import type { Panel as PanelSpec } from '../spec'
import { FieldRow, Section, Segmented } from './OptionsForm'

export const SWATCHES = ['green', 'amber', 'orange', 'red', 'blue', 'gray'] as const

export const COLORED = new Set(['timeseries', 'bar', 'pie', 'stat', 'gauge', 'table', 'heatmap'])
const schemesFor = (type?: string): Scheme[] =>
    type === 'heatmap'
        ? SCHEMES.filter((s) => s.kind === 'fixed' || s.kind === 'thresholds' || s.kind === 'continuous')
        : SCHEMES
const CELL_HINT: Record<string, string> = {
    fixed: 'One color, deeper where there is more',
    thresholds: 'Each cell takes its color from its value against the thresholds (Field tab)',
    continuous:
        "Each cell takes its color from where its value sits between min and max (Field tab), else the column's range",
}

export function ColorScheme({
    panel,
    frames,
    onChange,
}: {
    panel: PanelSpec
    frames: DataFrame[]
    onChange: (fc: PanelSpec['fieldConfig']) => void
}): JSX.Element {
    const theme = useChartTheme()
    const fc = panel.fieldConfig ?? {}
    const type = panel.viz?.type
    const cells = type === 'table' || type === 'heatmap'
    const base = defaultMode(type)
    const scheme = schemeOf(fc.color?.mode ?? base)
    const setColor = (c: Partial<NonNullable<typeof fc.color>> | undefined): void => {
        const next = c && { ...fc.color, mode: fc.color?.mode ?? base, ...c }
        onChange({ ...fc, color: next && (next.mode !== base || next.fixedColor || next.seriesBy) ? next : undefined })
    }
    const series = useMemo(() => {
        if (!frames.length || type === 'heatmap') {
            return []
        }
        if (type === 'table') {
            const cols = colorize(
                panel,
                withOverrides(
                    panel,
                    toTable(frames, panel.transforms ?? [])
                        .columns.filter((c) => c.type === 'number')
                        .map((c) => ({ label: c.name, name: c.name, data: [] as (number | null)[] }))
                ),
                theme.colors
            )
            return byValue(fc.color?.mode ?? base)
                ? cols.map((c) => ({ ...c, color: undefined as unknown as string }))
                : cols
        }
        const raw =
            panel.viz?.type === 'pie'
                ? (() => {
                      const c = toCategories(frames)
                      return c.labels.map((l, i) => ({ label: l, data: [c.series[0]?.data[i] ?? 0] }))
                  })()
                : toXSeries(frames).series
        return colorize(
            panel,
            withOverrides(
                panel,
                raw.map((x) => ({ ...x, name: x.label }))
            ),
            theme.colors
        ).slice(0, 24)
    }, [frames, panel.fieldConfig, panel.transforms, type, theme])
    const overrides = fc.overrides ?? {}
    const setSeriesColor = (name: string, color?: string): void => {
        const { color: _c, ...rest } = overrides[name] ?? {}
        const o = color ? { ...rest, color } : rest
        const next = { ...overrides }
        if (Object.keys(o).length) {
            next[name] = o
        } else {
            delete next[name]
        }
        onChange({ ...fc, overrides: Object.keys(next).length ? next : undefined })
    }
    const value = scheme.kind === 'thresholds' || scheme.kind === 'continuous'
    const hint =
        (type === 'heatmap' && CELL_HINT[scheme.kind]) ||
        (type === 'table' &&
            (CELL_HINT[scheme.kind === 'fixed' ? '' : scheme.kind] ?? scheme.hint?.replace(/\bseries\b/g, 'column'))) ||
        scheme.hint
    return (
        <Section title="Colors">
            <div className="grid grid-cols-[repeat(auto-fill,minmax(118px,1fr))] gap-1.5">
                {schemesFor(type).map((s) => (
                    <button
                        key={s.mode}
                        type="button"
                        title={s.hint ?? s.label}
                        aria-pressed={s.mode === scheme.mode}
                        data-attr={`dashboard-v2-scheme-${s.mode}`}
                        onClick={() => setColor({ mode: s.mode })}
                        className={`flex flex-col gap-1.5 rounded-md border p-1.5 text-left transition-colors ${s.mode === scheme.mode ? 'border-ring bg-fill-selected ring-1 ring-ring' : 'hover:bg-fill-hover'}`}
                    >
                        <Strip
                            scheme={s}
                            palette={theme.colors}
                            fixed={colorToken(fc.color?.fixedColor ?? 'blue')}
                            thresholds={(fc.thresholds ?? []).map((t) => colorToken(t.color))}
                        />
                        <span className="flex items-center gap-1 truncate text-[11px] font-medium">
                            {s.label}
                            {s.mode === scheme.mode && <IconCheck className="ml-auto size-3 shrink-0" />}
                        </span>
                    </button>
                ))}
            </div>
            {hint && <div className="text-[11px] text-muted-foreground">{hint}</div>}
            {(scheme.kind === 'fixed' || scheme.kind === 'shades') && (
                <FieldRow label="Color" inline>
                    <ColorSwatch color={fc.color?.fixedColor ?? 'blue'} onChange={(c) => setColor({ fixedColor: c })} />
                </FieldRow>
            )}
            {value && !cells && (
                <FieldRow
                    label="Color each series by"
                    description={
                        scheme.kind === 'continuous'
                            ? 'Where its value sits between min and max (Field tab), else the lowest and highest point'
                            : 'Its value against the thresholds (Field tab)'
                    }
                >
                    <Segmented
                        options={[
                            ['last', 'Last'],
                            ['mean', 'Mean'],
                            ['max', 'Max'],
                            ['min', 'Min'],
                        ]}
                        value={fc.color?.seriesBy ?? 'last'}
                        onChange={(v) => setColor({ seriesBy: v === 'last' ? undefined : (v as 'mean') })}
                    />
                </FieldRow>
            )}
            {series.length > 0 && (
                <div className="flex flex-col gap-1">
                    <div className="text-xs font-medium">{type === 'table' ? 'Columns' : 'Series'}</div>
                    <div className="text-[11px] text-muted-foreground">Click a color to set its own.</div>
                    <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-x-3 gap-y-1">
                        {series.map((s, i) => {
                            const own = withOverrides(panel, [{ label: s.name }])[0]?.o?.color ?? undefined
                            return (
                                <div key={i} className="flex min-w-0 items-center gap-1.5">
                                    <ColorSwatch
                                        small
                                        color={own}
                                        auto={s.color}
                                        onChange={(c) => setSeriesColor(s.name, c)}
                                    />
                                    <span
                                        className={`truncate text-xs ${own ? 'font-medium' : 'text-muted-foreground'}`}
                                        title={s.label}
                                    >
                                        {s.label}
                                    </span>
                                </div>
                            )
                        })}
                    </div>
                </div>
            )}
        </Section>
    )
}

function Strip({
    scheme: s,
    palette,
    fixed,
    thresholds,
}: {
    scheme: Scheme
    palette: string[]
    fixed: string
    thresholds: string[]
}): JSX.Element {
    const dots = (cs: string[]): JSX.Element => (
        <div className="flex h-4 gap-0.5">
            {cs.map((c, i) => (
                <span key={i} className="flex-1 rounded-sm" style={{ background: c }} />
            ))}
        </div>
    )
    if (s.kind === 'continuous') {
        return (
            <div className="h-4 rounded-sm" style={{ background: `linear-gradient(90deg, ${s.colors!.join(', ')})` }} />
        )
    }
    if (s.kind === 'fixed') {
        return dots([fixed])
    }
    if (s.kind === 'shades') {
        return dots([0, 0.2, 0.4, 0.6, 0.8].map((t) => along([fixed, '#ffffff'], t * 0.8)))
    }
    if (s.kind === 'thresholds') {
        return dots(thresholds.length ? thresholds : ['green', 'amber', 'red'].map(colorToken))
    }
    return dots((s.colors ?? palette).slice(0, 6))
}

export function ColorSwatch({
    color,
    auto,
    small,
    onChange,
}: {
    color?: string
    auto?: string
    small?: boolean
    onChange: (c: string | undefined) => void
}): JSX.Element {
    const css = color ? colorToken(color) : ''
    const shown = css || auto
    return (
        <Popover>
            <PopoverTrigger
                render={
                    <button
                        type="button"
                        className={`${small ? 'size-4 rounded' : 'size-7 rounded-md'} shrink-0 border shadow-xs ${shown ? '' : 'border-dashed bg-[repeating-linear-gradient(45deg,transparent_0_3px,var(--border)_3px_4px)]'} ${!css && auto ? 'ring-1 ring-border ring-offset-1' : ''}`}
                        style={shown ? { background: shown } : undefined}
                        aria-label={`Color ${color ?? 'automatic'}`}
                        title={color ?? 'Automatic'}
                    />
                }
            />
            <PopoverContent align="start" className="flex w-auto flex-col gap-2 p-2">
                <div className="flex gap-1.5">
                    {SWATCHES.map((c) => (
                        <button
                            key={c}
                            type="button"
                            title={c}
                            aria-label={c}
                            className={`size-6 rounded-md border ${c === color ? 'ring-2 ring-ring ring-offset-1' : ''}`}
                            style={{ background: colorToken(c) }}
                            onClick={() => onChange(c)}
                        />
                    ))}
                </div>
                <div className="flex items-center gap-2">
                    <label className="flex items-center gap-2 text-xs text-muted-foreground">
                        Custom{' '}
                        <input
                            type="color"
                            className="h-6 w-10 cursor-pointer rounded border bg-transparent"
                            value={
                                /^#[0-9a-f]{6}$/i.test(css)
                                    ? css
                                    : /^#[0-9a-f]{6}$/i.test(auto ?? '')
                                      ? auto
                                      : '#1d4aff'
                            }
                            onChange={(e) => onChange(e.target.value)}
                        />
                    </label>
                    {color && (
                        <Button variant="default" size="xs" className="ml-auto" onClick={() => onChange(undefined)}>
                            Auto
                        </Button>
                    )}
                </div>
            </PopoverContent>
        </Popover>
    )
}
