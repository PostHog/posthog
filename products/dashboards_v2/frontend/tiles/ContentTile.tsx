import { useCallback, useRef } from 'react'

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
    const { widgets, disabledReasonFor, onEdit } = useDashboardV2()
    const actions = useContentTileActions(id, widget)
    const canSetConfig = !disabledReasonFor('setWidgetConfig')
    // `onEdit` changes with every dashboard edit; a stable `setConfig` keeps `WidgetView`'s memo, so moving tiles
    // doesn't re-render every widget.
    const onEditRef = useRef(onEdit)
    onEditRef.current = onEdit
    const setConfig = useCallback((config: unknown) => onEditRef.current({ edit: 'setWidgetConfig', id, config }), [id])
    return (
        <WidgetCard
            widget={widget}
            widgets={widgets}
            actions={actions}
            editable={editable}
            setConfig={canSetConfig ? setConfig : undefined}
        />
    )
}
