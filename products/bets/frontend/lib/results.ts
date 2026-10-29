import { dayjs } from 'lib/dayjs'

import type { BetsResultIdeaApi, IdeaOutcomeEnumApi } from '../generated/api.schemas'
import type { BetWorkMark } from './workStatus'

export const OUTCOMES: Record<IdeaOutcomeEnumApi, { label: string; mark: BetWorkMark; tone: string }> = {
    won: { label: 'Won', mark: 'verified', tone: 'var(--success-foreground)' },
    lost: { label: 'Lost', mark: 'failed', tone: 'var(--destructive-foreground)' },
    flat: { label: 'No clear effect', mark: 'neutral', tone: 'var(--today-muted)' },
    harmed: { label: 'Stopped by a guardrail', mark: 'attention', tone: 'var(--warning-foreground)' },
    broken: { label: 'Broken test', mark: 'attention', tone: 'var(--warning-foreground)' },
    dropped: { label: 'Dropped', mark: 'cancelled', tone: 'var(--today-muted)' },
}

export function signedPercent(value: number): string {
    const rounded = Math.round(value * 100)
    return `${rounded > 0 ? '+' : rounded < 0 ? '−' : ''}${Math.abs(rounded)}%`
}

export interface EffectAxis {
    min: number
    max: number
    step: number
    ticks: number[]
}

const AXIS_STEPS = [0.05, 0.1, 0.2, 0.25, 0.5, 1, 2]

export function effectAxis(ideas: Pick<BetsResultIdeaApi, 'effect'>[]): EffectAxis {
    const bounds = ideas.flatMap((idea) => idea.effect ?? [])
    const low = Math.min(0, ...bounds)
    const high = Math.max(0, ...bounds)
    const fit = (step: number): EffectAxis => {
        const min = Math.min(-step, Math.floor(low / step - 1e-9) * step)
        const max = Math.max(step, Math.ceil(high / step - 1e-9) * step)
        const count = Math.round((max - min) / step)
        return { min, max, step, ticks: Array.from({ length: count + 1 }, (_, index) => min + index * step) }
    }
    return AXIS_STEPS.map(fit).find((axis) => axis.ticks.length <= 6) ?? fit(AXIS_STEPS[AXIS_STEPS.length - 1] * 2)
}

export function effectX(value: number, axis: EffectAxis, width: number): number {
    const clamped = Math.min(axis.max, Math.max(axis.min, value))
    return ((clamped - axis.min) / (axis.max - axis.min)) * width
}

export function elapsed(start: string, end: string): string {
    const minutes = Math.max(0, dayjs(end).diff(dayjs(start), 'minute'))
    if (minutes < 60) {
        return `${minutes} min`
    }
    if (minutes < 60 * 24) {
        return `${Math.floor(minutes / 60)} h ${minutes % 60} min`
    }
    const days = Math.round(minutes / (60 * 24))
    return `${days} ${days === 1 ? 'day' : 'days'}`
}

export function pullRequestNumber(url: string): string {
    const match = url.match(/\/pull\/(\d+)/)
    return match ? `#${match[1]}` : ''
}

export const PLOT_WIDTHS = { wide: 200, narrow: 144 }
const PLOT_GUTTER = 96

const LABEL_GLYPHS: Record<string, number> = { '%': 10.8, ' ': 3.5, t: 4.6, o: 7.4, '+': 7.6, '−': 7.6 }

export function labelWidth(text: string): number {
    return [...text].reduce((total, glyph) => total + (LABEL_GLYPHS[glyph] ?? 7.5), 0)
}

interface LabelPlacement {
    side: 'after' | 'before'
    crossesZero: boolean
}

export function labelPlacement(
    lower: number,
    upper: number,
    axis: EffectAxis,
    plot: number,
    text: string
): LabelPlacement {
    const width = labelWidth(text)
    const zero = effectX(0, axis, plot)
    const start = effectX(lower, axis, plot)
    const end = effectX(upper, axis, plot)
    const fitsAfter = end + 8 + width + 2 <= plot + PLOT_GUTTER
    const fitsBefore = start - 8 - width >= -12
    const side = fitsAfter || !fitsBefore ? 'after' : 'before'
    const [from, to] = side === 'after' ? [end + 8, end + 8 + width] : [start - 8 - width, start - 8]
    return { side, crossesZero: from - 3 < zero && zero < to + 3 }
}
