import { type ReactNode, useCallback, useState } from 'react'

import { IconChevronDown, IconChevronRight, IconDrag } from '@posthog/icons'
import { Button, Card, CardAction, CardContent, CardHeader, CardTitle, Input } from '@posthog/quill'

import { GRID, type SectionWidget, type Tile, spanPx } from '../dashboard/dashboardTypes'
import { useDashboardV2 } from '../dashboard/dashboardV2Context'
import type { OnSectionRows } from '../grid/TileGrid'
import { AddTileMenu } from './AddTileMenu'
import { TileContextMenu, hasTileMenu, useSectionActions } from './TileContextMenu'
import { TileMenuButton } from './TileMenuButton'

export interface SectionGridProps {
    gridId: string
    tiles: Tile[]
    cols: number
    width: number
    editable: boolean
    onLiveRows: (rows: number | null) => void
}

export function SectionTile({
    id,
    widget,
    columns,
    columnPx,
    editable,
    onSectionRows,
    renderGrid,
}: {
    id: string
    widget: SectionWidget
    columns: number
    columnPx: number
    editable: boolean
    onSectionRows: OnSectionRows
    /** Draws the section's own grid. Passed in because that grid draws sections too. */
    renderGrid: (grid: SectionGridProps) => ReactNode
}): JSX.Element {
    const { onEdit, onSectionFoldedChange, can } = useDashboardV2()
    const collapsed = !!widget.collapsed
    const [draft, setDraft] = useState<string | null>(null)
    const actions = useSectionActions(id, widget, () => setDraft(widget.title))
    const hasMenu = hasTileMenu(actions)
    const showAdd = editable && can('addTile')

    const onLiveRows = useCallback(
        (rows: number | null): void =>
            onSectionRows(
                id,
                rows === null
                    ? null
                    : Math.max(widget.minRows ?? 0, GRID.sectionChromeRows + Math.max(GRID.emptySectionRows, rows))
            ),
        [id, onSectionRows, widget.minRows]
    )

    const emptyLabel = editable ? 'Drag tiles here' : 'No tiles'

    return (
        <TileContextMenu actions={actions}>
            <Section collapsed={collapsed}>
                <SectionHeader
                    draggable={editable}
                    actions={
                        (showAdd || hasMenu) && (
                            <SectionActions>
                                {showAdd && <AddTileMenu gridId={id} />}
                                {hasMenu && <TileMenuButton />}
                            </SectionActions>
                        )
                    }
                >
                    <SectionTitle
                        title={widget.title}
                        collapsed={collapsed}
                        canEdit={editable && can('updateSection')}
                        onToggle={() => onSectionFoldedChange(id, !collapsed)}
                        onRename={(title) => onEdit({ edit: 'updateSection', id, patch: { title } })}
                        draft={draft}
                        onDraftChange={setDraft}
                    />
                    <SectionCount count={widget.tiles.length} />
                </SectionHeader>
                {!collapsed && (
                    <SectionBody emptyLabel={widget.tiles.length === 0 ? emptyLabel : null}>
                        {renderGrid({
                            gridId: id,
                            tiles: widget.tiles,
                            cols: columns,
                            width: spanPx(columns, columnPx) - 2 * GRID.sectionInsetPx,
                            editable,
                            onLiveRows,
                        })}
                    </SectionBody>
                )}
            </Section>
        </TileContextMenu>
    )
}

/** A section is a quill card, so it reads like a tile that holds tiles. */
export function Section({ collapsed, children }: { collapsed: boolean; children: ReactNode }): JSX.Element {
    return (
        <Card
            size="sm"
            role="group"
            className={collapsed ? 'DashboardV2__section DashboardV2__section--collapsed' : 'DashboardV2__section'}
            data-attr="dashboard-v2-section"
        >
            {children}
        </Card>
    )
}

/** The section's title bar, which is also what the section is dragged by. */
export function SectionHeader({
    draggable,
    actions,
    children,
}: {
    draggable: boolean
    actions?: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <CardHeader className="DashboardV2__section-header DashboardV2__handle">
            <div className="flex items-center gap-1 min-w-0">
                {draggable && <IconDrag className="DashboardV2__chrome size-4 shrink-0 text-muted-foreground" />}
                {children}
            </div>
            {actions}
        </CardHeader>
    )
}

export function SectionTitle({
    title,
    collapsed,
    canEdit,
    onToggle,
    onRename,
    draft,
    onDraftChange: setDraft,
}: {
    title: string
    collapsed: boolean
    canEdit: boolean
    onToggle: () => void
    onRename: (title: string) => void
    /** The title being typed, or null when not renaming. Held by the caller so its menu can start a rename. */
    draft: string | null
    onDraftChange: (draft: string | null) => void
}): JSX.Element {
    const commit = (): void => {
        if (draft !== null && draft.trim() && draft !== title) {
            onRename(draft.trim())
        }
        setDraft(null)
    }

    let label: JSX.Element
    if (draft !== null) {
        label = (
            <Input
                autoFocus
                className="quill-card__title h-6 w-56"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onBlur={commit}
                onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                        commit()
                    } else if (event.key === 'Escape') {
                        setDraft(null)
                    }
                }}
            />
        )
    } else if (canEdit) {
        label = (
            <Button
                size="xs"
                className="quill-card__title min-w-0 max-w-full"
                tooltip="Rename"
                data-attr="dashboard-v2-section-rename"
                onClick={() => setDraft(title)}
            >
                <span className="truncate">{title}</span>
            </Button>
        )
    } else {
        label = <CardTitle className="truncate">{title}</CardTitle>
    }

    return (
        <div className="flex items-center gap-1 min-w-0">
            <Button
                size="icon-xs"
                aria-label={collapsed ? 'Expand' : 'Collapse'}
                aria-expanded={!collapsed}
                data-attr="dashboard-v2-section-toggle"
                onClick={onToggle}
            >
                {collapsed ? <IconChevronRight /> : <IconChevronDown />}
            </Button>
            {label}
        </div>
    )
}

export function SectionCount({ count }: { count: number }): JSX.Element {
    return <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{count}</span>
}

/** Pushed to the end of the header, and shown only while the header is hovered or focused. */
export function SectionActions({ children }: { children: ReactNode }): JSX.Element {
    return <CardAction className="DashboardV2__chrome flex items-center gap-1">{children}</CardAction>
}

export function SectionBody({ emptyLabel, children }: { emptyLabel: string | null; children: ReactNode }): JSX.Element {
    return (
        <CardContent className="DashboardV2__section-body">
            {emptyLabel && (
                <span className="DashboardV2__section-empty text-sm text-muted-foreground">{emptyLabel}</span>
            )}
            {children}
        </CardContent>
    )
}
