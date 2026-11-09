import type { LegendItem } from '../../components/Legend/Legend'
import { mixColors, prefersLightText, toSrgbColor } from '../../core/color-utils'
import { DEFAULT_CHART_COLORS } from '../../core/theme'
import type { ChartTheme } from '../../core/types'
import { formatShare } from '../../utils/format'
import { classifyChange, type FlameDiffOptions, type FlameTree } from './flame-layout'
import type { FlameChangeKind } from './types'

export type FlameColorBy = 'group' | 'name' | 'diff'

export const MARK_NEW = 1
export const MARK_GONE = 2

/** Snapping diff fills to a few steps keeps the color math per step, not per node. */
const DIFF_STEPS = 8
const DIFF_FULL_RATIO = 2
/** Paler fills on light backgrounds so dark labels read on every hue, deeper ones on dark. */
const FILL_STRENGTH = { light: 0.45, dark: 0.6 }
const ANCESTOR_FADE = 0.45
const FALLBACK_BACKGROUND = '#ffffff'
const FALLBACK_INK = '#1d2330'

export interface FlameInk {
    background: string
    dark: boolean
    ink: string
    neutral: string
    slower: string
    faster: string
}

export function resolveInk(theme: ChartTheme): FlameInk {
    const palette = theme.colors.length > 0 ? theme.colors : DEFAULT_CHART_COLORS
    const diffPalette =
        palette.length > 4 && toSrgbColor(palette[4]) !== toSrgbColor(palette[0]) ? palette : DEFAULT_CHART_COLORS
    const background = toSrgbColor(theme.backgroundColor ?? FALLBACK_BACKGROUND)
    const dark = prefersLightText(background)
    // A host tooltip with inverted colors hands over an ink close to the background.
    const themeInk = toSrgbColor(theme.tooltipColor ?? FALLBACK_INK)
    const ink = prefersLightText(themeInk) !== dark ? themeInk : dark ? FALLBACK_BACKGROUND : FALLBACK_INK
    return {
        background,
        dark,
        ink,
        neutral: mixColors(background, ink, 0.14),
        slower: toSrgbColor(diffPalette[4]),
        faster: toSrgbColor(diffPalette[0]),
    }
}

export function resolveColorBy(tree: FlameTree<unknown>): FlameColorBy {
    if (tree.hasBaseline) {
        return 'diff'
    }
    return tree.hasGroups ? 'group' : 'name'
}

export interface FlameColors {
    /** Nodes share string instances, so a fill change is an identity check. */
    fills: string[]
    marks: Uint8Array
    legend: LegendItem[]
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
    colorBy: FlameColorBy,
    theme: ChartTheme,
    ink: FlameInk,
    diff: FlameDiffOptions,
    groupColors?: Record<string, string>
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
        const legend: LegendItem[] = [
            { key: 'slower', label: 'Slower', color: slower[DIFF_STEPS / 2] },
            { key: 'faster', label: 'Faster', color: faster[DIFF_STEPS / 2] },
            { key: 'similar', label: 'Similar', color: ink.neutral },
        ]
        if (seen.has('new')) {
            legend.push({
                key: 'new',
                label: 'New',
                color: ink.neutral,
                swatchClassName: 'border border-dashed border-current',
            })
        }
        if (seen.has('gone')) {
            legend.push({ key: 'gone', label: 'Gone', color: ink.neutral, swatchClassName: 'opacity-50' })
        }
        return { fills, marks, legend }
    }

    const palette = theme.colors.length > 0 ? theme.colors : DEFAULT_CHART_COLORS
    const strength = ink.dark ? FILL_STRENGTH.dark : FILL_STRENGTH.light
    const slotFills = palette.map((color) => blend(color, ink.background, strength))
    const customFills = new Map<string, string>()
    const customFill = (color: string): string =>
        cached(customFills, color, () => blend(color, ink.background, strength))
    const keyFills = new Map<string, string>()
    const selfByKey = new Map<string, number>()
    let nextSlot = 0
    for (let i = 0; i < tree.size; i++) {
        const node = tree.nodes[i]
        const key = colorBy === 'group' ? node.group : node.name
        let keyFill = key ? keyFills.get(key) : undefined
        if (key && keyFill === undefined) {
            const groupColor =
                colorBy === 'group' && groupColors && Object.hasOwn(groupColors, key) ? groupColors[key] : undefined
            keyFill = groupColor ? customFill(groupColor) : slotFills[nextSlot++ % slotFills.length]
            keyFills.set(key, keyFill)
        }
        fills[i] = node.color ? customFill(node.color) : (keyFill ?? ink.neutral)
        if (!key) {
            continue
        }
        // Laid-out widths, because concurrent children are scaled down to fit their parent.
        let selfWidth = tree.x1[i] - tree.x0[i]
        for (let c = tree.childStart[i], end = c + tree.childCount[i]; c < end; c++) {
            selfWidth -= tree.x1[c] - tree.x0[c]
        }
        selfByKey.set(key, (selfByKey.get(key) ?? 0) + Math.max(0, selfWidth))
    }

    const legend: LegendItem[] =
        colorBy === 'group'
            ? Array.from(keyFills, ([key, color]) => ({
                  key,
                  label: key,
                  color,
                  secondaryLabel: tree.totalValue > 0 ? formatShare(selfByKey.get(key) ?? 0) : undefined,
              })).sort((a, b) => (selfByKey.get(b.key) ?? 0) - (selfByKey.get(a.key) ?? 0))
            : []
    return { fills, marks, legend }
}

export interface FlameShades {
    searchMiss: string
    searchMissText: string
    textOn: (fill: string) => string
    ancestorOf: (fill: string) => string
}

export function createFlameShades(ink: FlameInk): FlameShades {
    const text = new Map<string, string>()
    const ancestor = new Map<string, string>()
    return {
        searchMiss: mixColors(ink.neutral, ink.background, 0.4),
        searchMissText: mixColors(ink.ink, ink.background, 0.55),
        textOn: (fill) => cached(text, fill, () => (prefersLightText(fill) === ink.dark ? ink.ink : ink.background)),
        ancestorOf: (fill) => cached(ancestor, fill, () => mixColors(fill, ink.background, ANCESTOR_FADE)),
    }
}

function cached(map: Map<string, string>, key: string, make: () => string): string {
    let value = map.get(key)
    if (value === undefined) {
        value = make()
        map.set(key, value)
    }
    return value
}
