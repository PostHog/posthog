export type DashboardAddTileKey = 'insight' | 'text' | 'image' | 'button' | 'widget' | 'group'

// pinned: autocapture data-attrs for the Add menu items, in the header and in empty groups
export const ADD_TILE_MENU_DATA_ATTRS: Record<DashboardAddTileKey, string> = {
    insight: 'dashboard-add-insight',
    text: 'dashboard-add-text-tile',
    image: 'dashboard-add-image-tile',
    button: 'dashboard-add-button-tile',
    widget: 'dashboard-add-widget',
    group: 'dashboard-add-tile-group',
}

/** Content adds a tile; layout organizes the tiles already there. */
export type DashboardAddTileSection = 'content' | 'layout'

export const DASHBOARD_ADD_TILE_SECTION_TITLES: Record<DashboardAddTileSection, string> = {
    content: 'Content',
    layout: 'Layout',
}

export interface DashboardAddTileOptionGroup {
    section: DashboardAddTileSection
    title: string
    options: DashboardAddTileOption[]
}

export function groupDashboardAddTileOptions(options: DashboardAddTileOption[]): DashboardAddTileOptionGroup[] {
    return (Object.keys(DASHBOARD_ADD_TILE_SECTION_TITLES) as DashboardAddTileSection[])
        .map((section) => ({
            section,
            title: DASHBOARD_ADD_TILE_SECTION_TITLES[section],
            options: options.filter((option) => option.section === section),
        }))
        .filter((group) => group.options.length > 0)
}

export interface DashboardAddTileOption {
    key: DashboardAddTileKey
    section: DashboardAddTileSection
    label: string
    tag?: 'new'
    onClick: () => void
}

export interface DashboardAddTileHandlers {
    onAddInsight: () => void
    onAddText: () => void
    onAddImage: () => void
    onAddButton: () => void
    setAddWidgetModalOpen: (open: boolean) => void
    /** Left out where the dashboard can't show tile groups. */
    onAddGroup?: () => void
}

/** What a dashboard can add, in menu order. The header's Add menu and the scene menu bar both render this list. */
export function getDashboardAddTileOptions({
    onAddInsight,
    onAddText,
    onAddImage,
    onAddButton,
    setAddWidgetModalOpen,
    onAddGroup,
}: DashboardAddTileHandlers): DashboardAddTileOption[] {
    const options: DashboardAddTileOption[] = [
        { key: 'insight', section: 'content', label: 'Charts', onClick: onAddInsight },
        { key: 'text', section: 'content', label: 'Add text', onClick: onAddText },
        { key: 'image', section: 'content', label: 'Image', onClick: onAddImage },
        { key: 'button', section: 'content', label: 'Button', onClick: onAddButton },
        { key: 'widget', section: 'content', label: 'Widget', onClick: () => setAddWidgetModalOpen(true) },
    ]
    if (onAddGroup) {
        options.push({
            key: 'group',
            section: 'layout',
            label: 'Group',
            tag: 'new',
            onClick: onAddGroup,
        })
    }
    return options
}
