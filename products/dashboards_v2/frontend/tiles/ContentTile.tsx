import type { ContentWidget } from '../dashboard/dashboardTypes'
import { useDashboardV2 } from '../dashboard/dashboardV2Context'
import { useContentTileActions } from './TileContextMenu'
import { WidgetCard } from './WidgetCard'

/** A widget card inside a dashboard, with the actions the dashboard allows on it. */
export function ContentTile({
    id,
    widget,
    editable,
}: {
    id: string
    widget: ContentWidget
    editable: boolean
}): JSX.Element {
    const { widgets } = useDashboardV2()
    const actions = useContentTileActions(id, widget)
    return <WidgetCard widget={widget} widgets={widgets} actions={actions} editable={editable} />
}
