import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

export type DashboardAddTileKey = 'insight' | 'text' | 'image' | 'button' | 'widget' | 'widget-preview'

export interface DashboardAddTileOption {
    key: DashboardAddTileKey
    label: string
    tag?: 'new' | 'beta'
    tooltip?: string
    onClick: () => void
}

export interface DashboardAddTileHandlers {
    dashboardWidgetsEnabled: boolean
    onAddInsight: () => void
    onAddText: () => void
    onAddImage: () => void
    onAddButton: () => void
    push: (url: string) => void
    setAddWidgetModalOpen: (open: boolean) => void
}

/** What a dashboard can add, in menu order. The header's Add menu and the scene menu bar both render this list. */
export function getDashboardAddTileOptions({
    dashboardWidgetsEnabled,
    onAddInsight,
    onAddText,
    onAddImage,
    onAddButton,
    push,
    setAddWidgetModalOpen,
}: DashboardAddTileHandlers): DashboardAddTileOption[] {
    return [
        { key: 'insight', label: 'Charts', onClick: onAddInsight },
        { key: 'text', label: 'Add text', onClick: onAddText },
        { key: 'image', label: 'Image', tag: 'new', onClick: onAddImage },
        { key: 'button', label: 'Button', onClick: onAddButton },
        dashboardWidgetsEnabled
            ? { key: 'widget', label: 'Widget', tag: 'new', onClick: () => setAddWidgetModalOpen(true) }
            : {
                  key: 'widget-preview',
                  label: 'Widget',
                  tag: 'beta',
                  tooltip: 'Opens settings to enable the Dashboard widgets beta',
                  onClick: () => push(urls.featurePreview(FEATURE_FLAGS.DASHBOARD_WIDGETS)),
              },
    ]
}
