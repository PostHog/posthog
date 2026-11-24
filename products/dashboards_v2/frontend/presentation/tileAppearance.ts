import type { ContentWidget } from '../dashboard/dashboardTypes'
import type { TileAction } from '../tiles/tileAction'
import type { WidgetAppearanceOptions } from '../widgets/widgetSpec'
import type { PresentationEdit } from './presentationEdits'

export function showsBackground(widget: ContentWidget, options: WidgetAppearanceOptions): boolean {
    return !options.background || widget.appearance?.background !== false
}

export function tileAppearanceAction(
    id: string,
    widget: ContentWidget,
    options: WidgetAppearanceOptions,
    disabledReason: string | null,
    onEdit: (edit: PresentationEdit) => void
): TileAction | null {
    if (!options.background) {
        return null
    }
    const background = showsBackground(widget, options)
    return {
        key: 'appearance',
        label: 'Appearance',
        group: 'display',
        dataAttr: 'dashboard-v2-tile-appearance',
        disabledReason,
        submenu: [
            {
                key: 'background',
                label: 'Background',
                dataAttr: 'dashboard-v2-tile-appearance-background',
                disabledReason,
                checked: background,
                onSelect: () =>
                    onEdit({
                        edit: 'setTileAppearance',
                        id,
                        appearance: { ...widget.appearance, background: !background },
                    }),
            },
        ],
    }
}
