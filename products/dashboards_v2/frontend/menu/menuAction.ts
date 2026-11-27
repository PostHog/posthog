export type MenuAction = {
    /**
     * Stable, so a panel type's `menuActions` or a host's `tileActions`, `tilePlacementActions` and `dashboardActions` can
     * find an action by it. Built in for a content tile: `download-image`, `copy-image`, `parts`, `background-color`, plus a chart's
     * `chart-type` and `chart-options`. Built in for a section: `rename`, `download-image`, `copy-image`, `auto-layout`, `parts`. Built
     * in for where a tile sits: `slideshow`, `move`, `add-to-tab`, `duplicate`, `remove`, and `remove` for a section. Built in for the
     * dashboard: `download-image`, `copy-image`, `tab-appearance`, `allow-filters`.
     */
    key: string
    label: string
    dataAttr: string
    disabledReason: string | null
    destructive?: boolean
    onSelect?: () => void
    submenu?: MenuAction[]
    /** Set on an action that is a toggle, or on one choice of a `choice` submenu: whether it is on. */
    checked?: boolean
    /** Set on a submenu whose entries are exclusive choices, such as a chart type. They show as radio items. */
    choice?: boolean
    /**
     * Where the action sits in the menu: `dashboard` for where the tile sits, `view` for looking at it or taking it
     * elsewhere, and `display` for how it looks. Left out, it sits with the other actions, first. A `destructive` action
     * always sits last, on its own.
     */
    group?: MenuGroup
    /** Set with `disabledReason` on an entry that is waiting, not refused. It shows a spinner in place of the reason. */
    loading?: boolean
    /** Draws or shows what the tile holds, so a tile's menu disables it while the tile is still loading. */
    needsLoaded?: boolean
    /** Picking it leaves the menu open, for a choice someone may want to compare with the next one. */
    keepOpen?: boolean
}

/** In menu order, after the ungrouped actions. */
export const MENU_GROUPS = [
    { group: 'dashboard', label: 'Dashboard' },
    { group: 'view', label: 'View & share' },
    { group: 'display', label: 'Display' },
] as const

export type MenuGroup = (typeof MENU_GROUPS)[number]['group']
