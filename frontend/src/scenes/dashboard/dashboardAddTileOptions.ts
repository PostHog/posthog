export type DashboardAddTileKey = 'insight' | 'text' | 'image' | 'button' | 'widget' | 'group'

export interface DashboardAddTileOption {
    key: DashboardAddTileKey
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
        { key: 'insight', label: 'Charts', onClick: onAddInsight },
        { key: 'text', label: 'Add text', onClick: onAddText },
        { key: 'image', label: 'Image', onClick: onAddImage },
        { key: 'button', label: 'Button', onClick: onAddButton },
        { key: 'widget', label: 'Widget', onClick: () => setAddWidgetModalOpen(true) },
    ]
    if (onAddGroup) {
        options.push({ key: 'group', label: 'Group', tag: 'new', onClick: onAddGroup })
    }
    return options
}
