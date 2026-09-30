import type { TodayWorkSectionId } from './todaySpacesLogic'

export type TodaySectionHeights = Record<TodayWorkSectionId, number>

export type PreferredTodaySectionHeights = Partial<Record<TodayWorkSectionId, number>>

export interface TodaySectionInput {
    id: TodayWorkSectionId
    open: boolean
    contentHeight: number
}

const FILL_ORDER: readonly TodayWorkSectionId[] = ['recent', 'spaces', 'pinned']

export const TODAY_SECTION_HEADER_HEIGHT = 36
const SHARE_CAP = 0.4
const MIN_FILL_HEIGHT = 56
const MIN_DRAG_HEIGHT = 40
const STRETCHING_SECTION: TodayWorkSectionId = 'recent'

function fillingSection(sections: readonly TodaySectionInput[]): TodayWorkSectionId | null {
    return FILL_ORDER.find((id) => sections.some((section) => section.id === id && section.open)) ?? null
}

export function layoutTodaySections(
    sections: readonly TodaySectionInput[],
    available: number,
    preferred: PreferredTodaySectionHeights = {}
): TodaySectionHeights {
    const heights: TodaySectionHeights = { pinned: 0, recent: 0, spaces: 0 }
    const fill = fillingSection(sections)
    if (fill === null || available <= 0) {
        return heights
    }

    const open = sections.filter((section) => section.open)
    const fillSection = open.find((section) => section.id === fill)
    if (!fillSection) {
        return heights
    }
    const others = open.filter((section) => section.id !== fill)
    const share = Math.round(available * SHARE_CAP)

    let used = 0
    for (const section of others) {
        const wanted = preferred[section.id] ?? share
        heights[section.id] = Math.floor(Math.max(0, Math.min(section.contentHeight, wanted)))
        used += heights[section.id]
    }

    const fillFloor = Math.min(fillSection.contentHeight, MIN_FILL_HEIGHT)
    if (available - used < fillFloor && used > 0) {
        const scale = Math.max(0, available - fillFloor) / used
        used = 0
        for (const section of others) {
            heights[section.id] = Math.floor(heights[section.id] * scale)
            used += heights[section.id]
        }
    }

    const rest = Math.max(0, available - used)
    heights[fill] = Math.floor(fill === STRETCHING_SECTION ? rest : Math.min(fillSection.contentHeight, rest))

    let leftover = available - used - heights[fill]
    for (const id of FILL_ORDER) {
        if (leftover <= 0) {
            break
        }
        const section = others.find((candidate) => candidate.id === id)
        if (!section || preferred[id] !== undefined) {
            continue
        }
        const grow = Math.floor(Math.min(leftover, section.contentHeight - heights[id]))
        if (grow <= 0) {
            continue
        }
        heights[id] += grow
        leftover -= grow
    }

    return heights
}

export function resizeTodaySections({
    sections,
    heights,
    upper,
    lower,
    delta,
    preferred,
}: {
    sections: readonly TodaySectionInput[]
    heights: TodaySectionHeights
    upper: TodayWorkSectionId
    lower: TodayWorkSectionId
    delta: number
    preferred: PreferredTodaySectionHeights
}): PreferredTodaySectionHeights {
    const contentOf = (id: TodayWorkSectionId): number =>
        sections.find((section) => section.id === id)?.contentHeight ?? 0
    const shrinkable = (id: TodayWorkSectionId): number => Math.max(0, heights[id] - MIN_DRAG_HEIGHT)
    const growable = (id: TodayWorkSectionId): number =>
        id === STRETCHING_SECTION ? Number.POSITIVE_INFINITY : Math.max(0, contentOf(id) - heights[id])
    const min = -Math.min(shrinkable(upper), growable(lower))
    const max = Math.min(growable(upper), shrinkable(lower))
    const applied = Math.max(min, Math.min(max, delta))
    const fill = fillingSection(sections)
    const next = { ...preferred }
    if (upper !== fill) {
        next[upper] = heights[upper] + applied
    }
    if (lower !== fill) {
        next[lower] = heights[lower] - applied
    }
    return next
}
