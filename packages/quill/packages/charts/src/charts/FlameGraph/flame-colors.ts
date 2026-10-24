import { rgb } from 'd3-color'

import { mixColors, prefersLightText, toSrgbColor } from '../../core/color-utils'
import { DEFAULT_CHART_COLORS } from '../../core/theme'
import type { ChartTheme } from '../../core/types'
import { classifyChange, type FlameDiffOptions, type FlameTree } from './flame-layout'
import type { FlameChangeKind, FlameColorBy } from './types'

export type ResolvedColorBy = Exclude<FlameColorBy, 'auto'>

/** Bitflags in {@link FlameColors.marks}. */
export const MARK_NEW = 1
export const MARK_GONE = 2

/** Diff fills are snapped to this many steps per direction, so 50,000 nodes share a few dozen
 *  color strings and the color math runs once per step instead of once per node. */
const DIFF_STEPS = 8
/** A change this many times the baseline, or this fraction of it, draws at full strength. */
const DIFF_FULL_RATIO = 2
/** Weight of the palette color over the background in a fill. Light backgrounds take paler fills,
 *  so dark labels read on every palette hue; dark backgrounds take deeper ones for light labels. */
const FILL_STRENGTH = { light: 0.45, dark: 0.6 }
const ANCESTOR_FADE = 0.45
const FALLBACK_BACKGROUND = '#ffffff'
const FALLBACK_INK = '#1d2330'
const MIN_INK_CONTRAST = 4.5

export interface FlameInk {
    background: string
    /** True when the background is dark. */
    dark: boolean
    /** Text color with the most contrast on the background. */
    ink: string
    /** Fill for neutral cells: similar, low sample, bundles. */
    neutral: string
    slower: string
    faster: string
}

export function resolveInk(theme: ChartTheme, slowerColor?: string, fasterColor?: string): FlameInk {
    const palette = theme.colors.length > 0 ? theme.colors : DEFAULT_CHART_COLORS
    const background = toSrgbColor(theme.backgroundColor ?? FALLBACK_BACKGROUND)
    const dark = prefersLightText(background)
    // `tooltipColor` is the host's foreground in the stock themes. A host whose tooltip inverts the
    // page colors would hand over a color close to the background, so fall back to a fixed ink.
    const themeInk = toSrgbColor(theme.tooltipColor ?? FALLBACK_INK)
    const ink =
        contrastRatio(themeInk, background) >= MIN_INK_CONTRAST ? themeInk : dark ? FALLBACK_BACKGROUND : FALLBACK_INK
    return {
        background,
        dark,
        ink,
        neutral: mixColors(background, ink, 0.14),
        slower: toSrgbColor(slowerColor ?? palette[4 % palette.length]),
        faster: toSrgbColor(fasterColor ?? palette[0]),
    }
}

export function resolveColorBy(tree: FlameTree<unknown>, colorBy: FlameColorBy | undefined): ResolvedColorBy {
    if (colorBy && colorBy !== 'auto') {
        return colorBy
    }
    if (tree.hasBaseline) {
        return 'diff'
    }
    return tree.hasGroups ? 'group' : 'name'
}

export interface FlameLegendEntry {
    key: string
    label: string
    color: string
    /** Draws the swatch with a dashed outline, like a new node. */
    dashed?: boolean
    /** Draws the swatch faded, like a gone node. */
    faded?: boolean
    /** Muted trailing text, for example a group's share of self value. */
    detail?: string
}

export interface FlameColors {
    /** Fill per node index. Nodes share string instances, so a fill change is an identity check. */
    fills: string[]
    /** {@link MARK_NEW} / {@link MARK_GONE} per node index. */
    marks: Uint8Array
    legend: FlameLegendEntry[]
}

function blend(color: string, background: string, strength: number): string {
    return mixColors(background, toSrgbColor(color), strength)
}

function diffStrength(ratio: number, threshold: number): number {
    const distance = Math.abs(Math.log(ratio)) - Math.log(1 + threshold)
    const span = Math.log(DIFF_FULL_RATIO)
    return Math.round(Math.min(1, Math.max(0, distance / span)) * DIFF_STEPS)
}

export function computeFlameColors(
    tree: FlameTree<unknown>,
    colorBy: ResolvedColorBy,
    theme: ChartTheme,
    ink: FlameInk,
    diff: FlameDiffOptions
): FlameColors {
    const fills: string[] = []
    const marks = new Uint8Array(tree.size)

    if (colorBy === 'diff') {
        const ramp = (target: string): string[] =>
            Array.from({ length: DIFF_STEPS + 1 }, (_, step) =>
                mixColors(ink.neutral, target, 0.3 + (0.7 * step) / DIFF_STEPS)
            )
        const slower = ramp(ink.slower)
        const faster = ramp(ink.faster)
        const seen = new Set<FlameChangeKind>()
        for (let i = 0; i < tree.size; i++) {
            const change = classifyChange(tree.nodes[i], diff)
            seen.add(change.kind)
            if (change.kind === 'slower' && change.ratio !== null) {
                fills[i] = slower[diffStrength(change.ratio, diff.threshold)]
            } else if (change.kind === 'faster' && change.ratio !== null) {
                fills[i] = faster[diffStrength(change.ratio, diff.threshold)]
            } else {
                fills[i] = ink.neutral
                marks[i] = change.kind === 'new' ? MARK_NEW : change.kind === 'gone' ? MARK_GONE : 0
            }
        }
        const legend: FlameLegendEntry[] = [
            { key: 'slower', label: 'Slower', color: slower[DIFF_STEPS / 2] },
            { key: 'faster', label: 'Faster', color: faster[DIFF_STEPS / 2] },
            { key: 'similar', label: 'Similar', color: ink.neutral },
        ]
        if (seen.has('new')) {
            legend.push({ key: 'new', label: 'New', color: ink.neutral, dashed: true })
        }
        if (seen.has('gone')) {
            legend.push({ key: 'gone', label: 'Gone', color: ink.neutral, faded: true })
        }
        return { fills, marks, legend }
    }

    const palette = theme.colors.length > 0 ? theme.colors : DEFAULT_CHART_COLORS
    const slotFills = palette.map((color) =>
        blend(color, ink.background, ink.dark ? FILL_STRENGTH.dark : FILL_STRENGTH.light)
    )
    const slots = new Map<string, number>()
    const selfByKey = new Map<string, number>()
    for (let i = 0; i < tree.size; i++) {
        const node = tree.nodes[i]
        const key = colorBy === 'group' ? node.group : node.name
        if (!key) {
            fills[i] = ink.neutral
            continue
        }
        let slot = slots.get(key)
        if (slot === undefined) {
            slot = slots.size % slotFills.length
            slots.set(key, slot)
        }
        fills[i] = slotFills[slot]
        selfByKey.set(key, (selfByKey.get(key) ?? 0) + tree.self[i])
    }

    const legend: FlameLegendEntry[] =
        colorBy === 'group'
            ? Array.from(slots, ([key, slot]) => ({
                  key,
                  label: key,
                  color: slotFills[slot],
                  detail: tree.totalValue > 0 ? formatShare((selfByKey.get(key) ?? 0) / tree.totalValue) : undefined,
              })).sort((a, b) => (selfByKey.get(b.key) ?? 0) - (selfByKey.get(a.key) ?? 0))
            : []
    return { fills, marks, legend }
}

export function formatShare(fraction: number): string {
    const percent = fraction * 100
    if (percent > 0 && percent < 0.1) {
        return '<0.1%'
    }
    return `${percent >= 10 ? Math.round(percent) : Math.round(percent * 10) / 10}%`
}

/** Derived colors keyed by fill, so each distinct fill runs the color math once. */
export class FlameShades {
    private readonly text = new Map<string, string>()
    private readonly ancestor = new Map<string, string>()
    /** Every node that misses an active search shares one hueless fill, so matches stand out by color. */
    readonly searchMiss: string
    readonly searchMissText: string

    constructor(private readonly ink: FlameInk) {
        this.searchMiss = mixColors(ink.neutral, ink.background, 0.4)
        this.searchMissText = mixColors(ink.ink, ink.background, 0.55)
    }

    textOn(fill: string): string {
        let color = this.text.get(fill)
        if (color === undefined) {
            const { ink, background } = this.ink
            color = contrastRatio(fill, ink) >= contrastRatio(fill, background) ? ink : background
            this.text.set(fill, color)
        }
        return color
    }

    /** Fill for an ancestor of the focused node, which spans the whole width. */
    ancestorOf(fill: string): string {
        return cached(this.ancestor, fill, () => mixColors(fill, this.ink.background, ANCESTOR_FADE))
    }
}

function relativeLuminance(color: string): number {
    const { r, g, b } = rgb(color)
    const channel = (v: number): number => {
        const c = (Number.isNaN(v) ? 0 : v) / 255
        return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
    }
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

/** WCAG 2 contrast. It picks the label color between the theme's ink and background, both of which
 *  sit at the ends of the lightness range, where WCAG 2 and APCA agree on the winner. */
function contrastRatio(a: string, b: string): number {
    const la = relativeLuminance(a)
    const lb = relativeLuminance(b)
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

function cached(map: Map<string, string>, key: string, make: () => string): string {
    let value = map.get(key)
    if (value === undefined) {
        value = make()
        map.set(key, value)
    }
    return value
}
