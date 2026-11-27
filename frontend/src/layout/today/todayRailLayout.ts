import type { TodayRailPane } from './todayShellLogic'

/** Always first on the rail and always shown, so there is one fixed way home. */
export const TODAY_RAIL_LOCKED_PANE: TodayRailPane = 'home'
/** Off the rail until a person turns them on: the PostHog AI button in the top bar is the main way into chats. */
export const TODAY_RAIL_DEFAULT_HIDDEN: TodayRailPane[] = ['spaces']
/** Pinned to the foot of the rail, outside the list a person arranges. */
export const TODAY_RAIL_FOOT_PANE: TodayRailPane = 'products'

/** How a person arranged the rail: their order, null until they move a pane, and the panes they hid. */
export interface TodayRailLayout {
    order: TodayRailPane[] | null
    hidden: TodayRailPane[]
}

export const TODAY_RAIL_DEFAULT_LAYOUT: TodayRailLayout = { order: null, hidden: TODAY_RAIL_DEFAULT_HIDDEN }

export function toggleHiddenPane(layout: TodayRailLayout, pane: TodayRailPane): TodayRailLayout {
    if (pane === TODAY_RAIL_LOCKED_PANE) {
        return layout
    }
    const hidden = layout.hidden.includes(pane)
        ? layout.hidden.filter((other) => other !== pane)
        : [...layout.hidden, pane]
    return { ...layout, hidden }
}

/** The panes a person can show, hide and move, in their order. */
export function arrangeablePanes(order: TodayRailPane[] | null, railPanes: TodayRailPane[]): TodayRailPane[] {
    const panes = railPanes.filter((pane) => pane !== TODAY_RAIL_LOCKED_PANE && pane !== TODAY_RAIL_FOOT_PANE)
    if (!order) {
        return panes
    }
    const known = order.filter((pane) => panes.includes(pane))
    // A pane a flag turns on later lands where it sits by default, after the panes that came before it.
    return panes.reduce((arranged, pane) => {
        if (arranged.includes(pane)) {
            return arranged
        }
        const before = panes.slice(0, panes.indexOf(pane)).filter((other) => arranged.includes(other))
        const at = before.length ? arranged.indexOf(before[before.length - 1]) + 1 : 0
        return [...arranged.slice(0, at), pane, ...arranged.slice(at)]
    }, known)
}

export function movePane(panes: TodayRailPane[], pane: TodayRailPane, toIndex: number): TodayRailPane[] {
    const rest = panes.filter((other) => other !== pane)
    const at = Math.max(0, Math.min(toIndex, rest.length))
    return [...rest.slice(0, at), pane, ...rest.slice(at)]
}
