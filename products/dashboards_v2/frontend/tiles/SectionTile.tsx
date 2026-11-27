import './SectionTile.css'

import clsx from 'clsx'
import { type ReactNode, useCallback, useMemo, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    Card,
    CardContent,
    CardHeader,
    Input,
} from '@posthog/quill'

import { useDashboard } from '../dashboard/core/dashboardContext'
import {
    GRID,
    type SectionPanel,
    type Tile,
    isSection,
    sectionDescriptionRows,
    spanPx,
} from '../dashboard/document/dashboardTypes'
import { everyTile } from '../dashboard/document/tileTree'
import type { OnSectionRows } from '../grid/TileGrid'
import { DESCRIPTION_IMAGE_ONLY_CLASS, DescriptionInfo } from './core/ContentTile'
import { TileActions } from './core/TileActions'
import { showsBorder, tileBackgroundStyle } from './core/tileAppearance'
import { TileContextMenu, hasTileMenu } from './core/TileContextMenu'
import { AddTileMenu } from './menu/AddTileMenu'
import { useSectionActions, useSectionPlacementActions } from './menu/tileMenuActions'

export type SectionGridProps = {
    gridId: string
    tiles: Tile[]
    cols: number
    width: number
    editable: boolean
    onLiveRows: (rows: number | null) => void
}

export function SectionTile({
    id,
    panel,
    layout,
    editable,
    onSectionRows,
    renderGrid,
}: {
    id: string
    panel: SectionPanel
    /** The section's width in grid columns, and the width of one column in pixels. */
    layout: { columns: number; columnPx: number }
    editable: boolean
    onSectionRows: OnSectionRows
    /** Draws the section's own grid. Passed in because that grid draws sections too. */
    renderGrid: (grid: SectionGridProps) => ReactNode
}): JSX.Element {
    const { onEdit, onSectionFoldedChange, can } = useDashboard()
    const collapsed = !!panel.collapsed
    const descriptionMode = panel.appearance?.description ?? 'icon'
    const description = descriptionMode === 'hidden' ? undefined : panel.description
    const [draft, setDraft] = useState<string | null>(null)
    const ownActions = useSectionActions(id, panel, () => setDraft(panel.title))
    const [confirmingRemove, setConfirmingRemove] = useState(false)
    const placementActions = useSectionPlacementActions(id, panel, () => setConfirmingRemove(true))
    const actions = useMemo(() => [...ownActions, ...placementActions], [ownActions, placementActions])
    const hasMenu = hasTileMenu(actions)
    const showAdd = can('addTile')

    const onLiveRows = useCallback(
        (rows: number | null): void =>
            onSectionRows(
                id,
                rows === null
                    ? null
                    : Math.max(
                          panel.minRows ?? 0,
                          GRID.sectionChromeRows + sectionDescriptionRows(panel) + Math.max(GRID.emptySectionRows, rows)
                      )
            ),
        [id, onSectionRows, panel]
    )

    const emptyLabel = editable ? 'Drag tiles here' : 'No tiles'

    return (
        <>
            {/* Outside the menu's trigger, so a right-click in the dialog does not open the section's menu. */}
            <AlertDialog open={confirmingRemove} onOpenChange={setConfirmingRemove}>
                <AlertDialogContent data-attr="dashboard-v2-section-remove-confirm">
                    <AlertDialogHeader>
                        <AlertDialogTitle>Remove this section and its tiles?</AlertDialogTitle>
                        <AlertDialogDescription>{removeWarning(panel)}</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                        <AlertDialogClose
                            render={<Button variant="destructive-outline" />}
                            data-attr="dashboard-v2-section-remove-confirm-button"
                            onClick={() => onEdit({ edit: 'removeTile', id })}
                        >
                            Remove section
                        </AlertDialogClose>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
            <TileContextMenu actions={actions}>
                <Section border={showsBorder(panel)} backgroundColor={panel.appearance?.backgroundColor}>
                    <SectionHeader
                        description={
                            description &&
                            descriptionMode === 'below' && (
                                <DescriptionInfo
                                    description={description}
                                    className="SectionTile__description TileGrid__text truncate text-left text-xs text-muted-foreground"
                                >
                                    {description}
                                </DescriptionInfo>
                            )
                        }
                        actions={
                            (showAdd || hasMenu) && (
                                <TileActions menu={hasMenu}>{showAdd && <AddTileMenu gridId={id} />}</TileActions>
                            )
                        }
                    >
                        <SectionTitle
                            title={panel.title}
                            collapsed={collapsed}
                            canEdit={can('updateSection')}
                            onToggle={() => onSectionFoldedChange(id, !collapsed)}
                            onRename={(title) => onEdit({ edit: 'updateSection', id, patch: { title } })}
                            draft={draft}
                            onDraftChange={setDraft}
                        />
                        {/* An open section shows its tiles, so the count only says something once it is closed. */}
                        {collapsed && <SectionCount count={panel.tiles.length} />}
                        {description && descriptionMode === 'icon' && <DescriptionInfo description={description} />}
                        {description && descriptionMode === 'icon' && (
                            <span className={clsx(DESCRIPTION_IMAGE_ONLY_CLASS, DESCRIPTION_TEXT)}>{description}</span>
                        )}
                    </SectionHeader>
                    {!collapsed && (
                        <SectionBody emptyLabel={panel.tiles.length === 0 ? emptyLabel : null}>
                            {renderGrid({
                                gridId: id,
                                tiles: panel.tiles,
                                cols: layout.columns,
                                width: spanPx(layout.columns, layout.columnPx) - 2 * GRID.sectionInsetPx,
                                editable,
                                onLiveRows,
                            })}
                        </SectionBody>
                    )}
                </Section>
            </TileContextMenu>
        </>
    )
}

function removeWarning(panel: SectionPanel): string {
    const count = everyTile(panel.tiles).filter((tile) => !isSection(tile)).length
    const tiles = count === 1 ? 'the 1 tile' : `the ${count} tiles`
    return `This removes "${panel.title}" and ${tiles} in it from the dashboard.`
}

/** A section is a quill card, so it reads like a tile that holds tiles. */
export function Section({
    border = true,
    backgroundColor,
    children,
}: {
    border?: boolean
    backgroundColor?: string
    children: ReactNode
}): JSX.Element {
    return (
        <Card
            size="sm"
            role="group"
            className={border ? 'SectionTile' : 'SectionTile SectionTile--no-border'}
            style={tileBackgroundStyle(backgroundColor)}
            data-attr="dashboard-v2-section"
        >
            {children}
        </Card>
    )
}

// A long title stops here, so the count, the description and the actions keep their room in the header.
const TITLE_MAX_WIDTH = 'max-w-96'

// It starts from no width and takes what the title and count leave, so a long description never cuts the title short.
const DESCRIPTION_TEXT = 'TileGrid__text min-w-0 flex-1 basis-0 truncate text-xs text-muted-foreground'

/** The section's title bar, which is also what the section is dragged by. */
export function SectionHeader({
    actions,
    description,
    children,
}: {
    actions?: ReactNode
    /** Shown on its own line under the title. The header is one grid row and gap taller with it. */
    description?: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <CardHeader
            className={clsx('SectionTile__header TileGrid__handle', description && 'SectionTile__header--described')}
        >
            <div className="flex items-center gap-1 min-w-0">{children}</div>
            {description}
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
                className={clsx('quill-card__title min-w-0 shrink', TITLE_MAX_WIDTH)}
                // The title is cut off past its width, so the tooltip is where the whole of it shows.
                tooltip={`Rename "${title}"`}
                data-attr="dashboard-v2-section-rename"
                onClick={() => setDraft(title)}
            >
                <span className="truncate">{title}</span>
            </Button>
        )
    } else {
        label = (
            // A tap opens the whole title, because a touch screen has no hover to show what the header cuts off.
            <DescriptionInfo
                description={title}
                className={clsx('quill-card__title TileGrid__text truncate text-left', TITLE_MAX_WIDTH)}
            >
                {title}
            </DescriptionInfo>
        )
    }

    return (
        <div className="flex items-center gap-1 min-w-0">
            <Button
                size="icon-xs"
                className="SectionTile__toggle"
                aria-label={collapsed ? 'Expand' : 'Collapse'}
                aria-expanded={!collapsed}
                data-attr="dashboard-v2-section-toggle"
                onClick={onToggle}
            >
                {/* One icon turned, because the down chevron's glyph is drawn smaller than the right one. */}
                <IconChevronRight
                    className={clsx('transition-transform motion-reduce:transition-none', !collapsed && 'rotate-90')}
                />
            </Button>
            {label}
        </div>
    )
}

export function SectionCount({ count }: { count: number }): JSX.Element {
    return <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{count}</span>
}

export function SectionBody({ emptyLabel, children }: { emptyLabel: string | null; children: ReactNode }): JSX.Element {
    return (
        <CardContent className="SectionTile__body">
            {emptyLabel && <span className="SectionTile__empty text-sm text-muted-foreground">{emptyLabel}</span>}
            {children}
        </CardContent>
    )
}
