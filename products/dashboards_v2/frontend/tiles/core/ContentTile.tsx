import './ContentTile.css'

import clsx from 'clsx'
import { type CSSProperties, type ReactNode, useMemo, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    Card,
    CardContent,
    CardDescription,
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
import { TileBackgroundContext } from '../../panels/core/tileBackground'
import { TileActions } from './TileActions'
import { NO_BACKGROUND, showsBorder, tileBackgroundColor, tileBackgroundStyle } from './tileAppearance'
import { TileContextMenu, hasTileMenu } from './TileContextMenu'
import { isPartShown } from './tileParts'

export const INTERACTIVE_ONLY_CLASS = 'dash-ContentTile--interactive-only'
/** An image has no hover, so it leaves the description icon out and shows the description under the title instead. */
/** On a description's text that only an image or a printed page shows, in place of the icon. */
export const DESCRIPTION_IMAGE_ONLY_CLASS = 'dash-ContentTile__description--image-only'
export const DESCRIPTION_ICON_CLASS = 'dash-ContentTile__description-icon'

const NO_ACTIONS: MenuAction[] = []

function cardLook(
    panel: SavedPanel,
    customizations: TileCustomization[],
    fromPanel: string | null
): { className: string; style: CSSProperties | undefined } {
    const color = fromPanel ?? tileBackgroundColor(panel, customizations)
    return {
        className: clsx(
            color === NO_BACKGROUND && 'dash-ContentTile--no-background',
            !showsBorder(panel) && 'dash-ContentTile--no-border'
        ),
        style: tileBackgroundStyle(color),
    }
}

/** Opens the description on hover or click. Its trigger is the info icon, or `children` when a caller shows cut-off text instead. */
export function DescriptionInfo({
    description,
    className,
    children,
}: {
    description: string
    className?: string
    children?: ReactNode
}): JSX.Element {
    const [open, setOpen] = useState(false)
    return (
        <Tooltip open={open} onOpenChange={setOpen}>
            <TooltipTrigger
                // A touch screen has no hover, so a click opens the description and must not close it again.
                closeOnClick={false}
                render={
                    <button
                        type="button"
                        className={
                            className ?? clsx(DESCRIPTION_ICON_CLASS, 'inline-flex shrink-0 text-muted-foreground')
                        }
                        aria-label={description}
                        onClick={() => setOpen(true)}
                    />
                }
            >
                {children ?? <IconInfo />}
            </TooltipTrigger>
            <TooltipContent className="max-w-80">
                <span className="line-clamp-6">{description}</span>
            </TooltipContent>
        </Tooltip>
    )
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
    const [backgroundFromPanel, setBackgroundFromPanel] = useState<string | null>(null)
    const look = cardLook(panel, definition?.allowedCustomizations ?? [], backgroundFromPanel)
    const descriptionMode = panel.appearance?.description ?? 'icon'
    const description = descriptionMode === 'hidden' ? undefined : panel.description
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
                            {description && descriptionMode === 'icon' && <DescriptionInfo description={description} />}
                        </CardTitle>
                        {description && (
                            <CardDescription
                                className={clsx(
                                    'dash-ContentTile__description TileGrid__text',
                                    descriptionMode === 'icon' && DESCRIPTION_IMAGE_ONLY_CLASS
                                )}
                                title={description}
                            >
                                {description}
                            </CardDescription>
                        )}
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
                    <TileBackgroundContext.Provider value={setBackgroundFromPanel}>
                        <PanelView panel={panel} definition={definition} setConfig={setConfig} />
                    </TileBackgroundContext.Provider>
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
