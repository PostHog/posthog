export interface MenuAction {
    /**
     * Stable, so a widget type or host can find an action by it in `tileActions` or `dashboardActions`. Built in for a
     * content tile: `move`, `parts`, `appearance`, `remove`, plus a chart's `chart-type` and `chart-options`. Built in
     * for a section: `rename`, `remove`. Built in for the dashboard: `download-image`.
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
     * Where the action sits in the menu: `display` for how the tile looks, such as which parts show or a chart's type.
     * Left out, it sits with the other actions. A `destructive` action always sits last, on its own.
     */
    group?: 'display'
}
