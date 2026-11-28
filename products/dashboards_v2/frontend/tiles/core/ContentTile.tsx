import './ContentTile.css'

import clsx from 'clsx'
import { type CSSProperties, useMemo } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    Card,
    CardContent,
    CardFooter,
    CardHeader,
    CardTitle,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import type { MenuAction } from '../../menu/menuAction'
import { type PanelType, panelSlots } from '../../panels/core/panelDefinition'
import { PanelErrorBoundary } from '../../panels/core/PanelErrorBoundary'
import { type SavedPanel } from '../../panels/core/panelSchema'
import { type TileCustomization, findPanel } from '../../panels/core/panelSpec'
import { PanelView } from '../../panels/core/PanelView'
import { TileActions } from './TileActions'
import { NO_BACKGROUND, showsBorder, tileBackgroundColor } from './tileAppearance'
import { TileContextMenu, hasTileMenu } from './TileContextMenu'
import { isPartShown } from './tileParts'

export const INTERACTIVE_ONLY_CLASS = 'dash-ContentTile--interactive-only'

const NO_ACTIONS: MenuAction[] = []

function cardLook(
    panel: SavedPanel,
    customizations: TileCustomization[]
): { className: string; style: CSSProperties | undefined } {
    const color = tileBackgroundColor(panel, customizations)
    const tint = color === NO_BACKGROUND ? null : color
    return {
        className: clsx(
            color === NO_BACKGROUND && 'dash-ContentTile--no-background',
            !showsBorder(panel) && 'dash-ContentTile--no-border',
            tint && 'dash-ContentTile--tinted'
        ),
        // A saved color can be any CSS color, so no class can carry it.
        style: tint ? ({ '--dv2-tile-background-color': tint } as CSSProperties) : undefined,
    }
}

/**
 * One panel in its card: header, body and footer. It reads no dashboard, so a page can render a single panel on
 * its own. Inside a dashboard, `DashboardContentTile` passes both kinds of actions.
 */
export function ContentTile({
    panel,
    panels,
    actions = NO_ACTIONS,
    placementActions = NO_ACTIONS,
    editable = false,
    setConfig,
}: {
    panel: SavedPanel
    /** The panel types the page can show. The card renders the one that `panel.type` names. */
    panels: PanelType[]
    /** What a person can do to the tile itself, such as change its chart type. Shown on right-click. */
    actions?: MenuAction[]
    /** What a person can do to where the tile sits, such as move or remove it. Left out on a tile outside a dashboard. */
    placementActions?: MenuAction[]
    editable?: boolean
    /** Lets a panel that edits in place, such as text, save its config. Left out, the panel is read-only. */
    setConfig?: (config: unknown) => void
}): JSX.Element {
    const definition = findPanel(panels, panel.type)
    const slots = panelSlots(definition)
    const showHeader = isPartShown(panel, 'header', slots)
    const showFooter = isPartShown(panel, 'footer', slots)
    const look = cardLook(panel, definition?.allowedCustomizations ?? [])
    const HeaderExtra = definition?.HeaderExtra
    const Footer = definition?.Footer
    // Placement goes first so the slideshow stays above the image download in the shared view group.
    const menu = useMemo(() => [...placementActions, ...actions], [actions, placementActions])
    const hasMenu = hasTileMenu(menu)

    return (
        <TileContextMenu actions={menu}>
            <Card
                size="sm"
                // A tile without a header has no title bar, so the whole tile is what it is dragged by.
                className={clsx(
                    'dash-ContentTile',
                    look.className,
                    editable && !showHeader && 'TileGrid__handle',
                    definition?.showOnInteractiveOnly(panel) && INTERACTIVE_ONLY_CLASS
                )}
                style={look.style}
            >
                {showHeader && (
                    <CardHeader className={clsx(editable && 'TileGrid__handle')}>
                        <CardTitle className="flex items-center gap-1 min-w-0">
                            <span className="TileGrid__text truncate">{panel.title}</span>
                            {panel.description && (
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <span
                                                tabIndex={0}
                                                className="inline-flex shrink-0 text-muted-foreground"
                                                aria-label={panel.description}
                                            />
                                        }
                                    >
                                        <IconInfo />
                                    </TooltipTrigger>
                                    <TooltipContent className="max-w-80">{panel.description}</TooltipContent>
                                </Tooltip>
                            )}
                        </CardTitle>
                        {(HeaderExtra || hasMenu) && (
                            <TileActions menu={hasMenu}>
                                {HeaderExtra && (
                                    <PanelErrorBoundary panel={panel} fallback={null}>
                                        <HeaderExtra panel={panel} />
                                    </PanelErrorBoundary>
                                )}
                            </TileActions>
                        )}
                    </CardHeader>
                )}
                {!showHeader && hasMenu && <TileActions menu className="dash-ContentTile__float-toolbar" />}
                <CardContent className="flex flex-col flex-1 min-h-0 overflow-hidden">
                    <PanelView panel={panel} definition={definition} setConfig={setConfig} />
                </CardContent>
                {showFooter && (
                    // The grid's drag cancel selector lists this class, so a tile dragged by its body never starts a drag here.
                    <CardFooter className="dash-ContentTile__footer flex shrink-0 items-center gap-2 min-w-0 text-xs text-secondary">
                        {Footer && (
                            <PanelErrorBoundary panel={panel} fallback={null}>
                                <Footer panel={panel} />
                            </PanelErrorBoundary>
                        )}
                    </CardFooter>
                )}
            </Card>
        </TileContextMenu>
    )
}
