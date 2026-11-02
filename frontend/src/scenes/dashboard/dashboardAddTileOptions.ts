export type DashboardAddTileKey = 'insight' | 'text' | 'image' | 'button' | 'widget'

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
}

/** What a dashboard can add, in menu order. The header's Add menu and the scene menu bar both render this list. */
export function getDashboardAddTileOptions({
    onAddInsight,
    onAddText,
    onAddImage,
    onAddButton,
    setAddWidgetModalOpen,
}: DashboardAddTileHandlers): DashboardAddTileOption[] {
    return [
        { key: 'insight', label: 'Charts', onClick: onAddInsight },
        { key: 'text', label: 'Add text', onClick: onAddText },
        { key: 'image', label: 'Image', tag: 'new', onClick: onAddImage },
        { key: 'button', label: 'Button', onClick: onAddButton },
        { key: 'widget', label: 'Widget', tag: 'new', onClick: () => setAddWidgetModalOpen(true) },
    ]
}
