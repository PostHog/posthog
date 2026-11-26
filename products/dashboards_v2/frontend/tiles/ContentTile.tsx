import { useCallback, useRef } from 'react'

import type { ContentPanel } from '../dashboard/dashboardTypes'
import { useDashboardV2 } from '../dashboard/dashboardV2Context'
import { PanelCard } from './PanelCard'
import { useContentTileActions } from './TileContextMenu'

/** A panel card inside a dashboard, with the actions the dashboard allows on it. */
export function ContentTile({
    id,
    panel,
    editable,
}: {
    id: string
    panel: ContentPanel
    editable: boolean
}): JSX.Element {
    const { panels, disabledReasonFor, onEdit } = useDashboardV2()
    const actions = useContentTileActions(id, panel)
    const canSetConfig = !disabledReasonFor('setPanelConfig')
    // `onEdit` changes with every dashboard edit; a stable `setConfig` keeps `PanelView`'s memo, so moving tiles
    // doesn't re-render every panel.
    const onEditRef = useRef(onEdit)
    onEditRef.current = onEdit
    const setConfig = useCallback((config: unknown) => onEditRef.current({ edit: 'setPanelConfig', id, config }), [id])
    return (
        <PanelCard
            panel={panel}
            panels={panels}
            actions={actions}
            editable={editable}
            setConfig={canSetConfig ? setConfig : undefined}
        />
    )
}
