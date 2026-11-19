import { useActions } from 'kea'
import { useCallback } from 'react'

import { IconDrag, IconTrash } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { dashboardV2Logic } from '../dashboardV2Logic'
import { GRID, type SectionWidget, spanPx } from '../layout/dashboardTypes'
import { AddTileMenu } from './AddTileMenu'
import { SectionTitle } from './SectionTitle'
import { TileGrid } from './TileGrid'

export function SectionTile({
    id,
    widget,
    columns,
    columnPx,
    editable,
    onSectionRows,
}: {
    id: string
    widget: SectionWidget
    columns: number
    columnPx: number
    editable: boolean
    onSectionRows: (id: string, rows: number | null) => void
}): JSX.Element {
    const { applyDashboardEdit } = useActions(dashboardV2Logic)
    const collapsed = !!widget.collapsed

    const onLiveRows = useCallback(
        (rows: number | null): void =>
            onSectionRows(id, rows === null ? null : 1 + Math.max(GRID.emptySectionRows, rows)),
        [id, onSectionRows]
    )

    return (
        <section className="DashboardV2__section" data-attr="dashboard-v2-section">
            <header className="DashboardV2__section-header DashboardV2__handle">
                {editable && <IconDrag className="DashboardV2__chrome size-4 shrink-0 text-muted-foreground" />}
                <SectionTitle
                    title={widget.title}
                    collapsed={collapsed}
                    canEdit={editable}
                    onToggle={() => applyDashboardEdit({ edit: 'updateSection', id, patch: { collapsed: !collapsed } })}
                    onRename={(title) => applyDashboardEdit({ edit: 'updateSection', id, patch: { title } })}
                />
                <span className="text-xs text-muted-foreground tabular-nums">{widget.tiles.length}</span>
                <div className="flex-1" />
                {editable && (
                    <div className="DashboardV2__chrome flex items-center gap-1">
                        <AddTileMenu gridId={id} />
                        <Button
                            size="icon-xs"
                            tooltip="Remove section and its tiles"
                            aria-label="Remove section"
                            data-attr="dashboard-v2-section-remove"
                            onClick={() => applyDashboardEdit({ edit: 'removeTile', id })}
                        >
                            <IconTrash />
                        </Button>
                    </div>
                )}
            </header>
            {!collapsed && (
                <div className="DashboardV2__section-body">
                    {widget.tiles.length === 0 && (
                        <span className="DashboardV2__section-empty text-sm text-muted-foreground">
                            {editable ? 'Drag tiles here' : 'No tiles'}
                        </span>
                    )}
                    <TileGrid
                        gridId={id}
                        tiles={widget.tiles}
                        cols={columns}
                        width={spanPx(columns, columnPx)}
                        editable={editable}
                        onLiveRows={onLiveRows}
                    />
                </div>
            )}
        </section>
    )
}
