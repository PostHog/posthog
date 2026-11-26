import './PanelCard.css'
import './TileHoverReveal.css'

import clsx from 'clsx'
import type { CSSProperties } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    Card,
    CardAction,
    CardContent,
    CardFooter,
    CardHeader,
    CardTitle,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import type { ContentPanel } from '../dashboard/dashboardTypes'
import type { MenuAction } from '../dashboard/menuAction'
import { type PanelDefinition, panelSlots } from '../panels/panelDefinition'
import { type PanelAppearanceOptions, findPanel } from '../panels/panelSpec'
import { PanelView } from '../panels/PanelView'
import { showsBackground, showsBorder, tileBackgroundColor } from '../presentation/tileAppearance'
import { isPartShown } from '../presentation/tileParts'
import { TileContextMenu, hasTileMenu } from './TileContextMenu'
import { TileMenuButton } from './TileMenuButton'

function UpdatedAt({ refreshedAt }: { refreshedAt?: string }): JSX.Element {
    if (!refreshedAt) {
        return <span className="shrink-0">Not refreshed yet</span>
    }
    return (
        <span className="shrink-0">
            Updated <TZLabel time={refreshedAt} />
        </span>
    )
}

function cardLook(
    panel: ContentPanel,
    options: PanelAppearanceOptions
): { className: string; style: CSSProperties | undefined } {
    const backgroundColor = tileBackgroundColor(panel, options)
    return {
        className: clsx(
            !showsBackground(panel, options) && 'dash-PanelCard--no-background',
            !showsBorder(panel) && 'dash-PanelCard--no-border',
            backgroundColor && 'dash-PanelCard--tinted'
        ),
        // A saved color can be any CSS color, so no class can carry it.
        style: backgroundColor ? ({ '--dv2-tile-background-color': backgroundColor } as CSSProperties) : undefined,
    }
}

/**
 * One panel in its card: header, body and footer. It reads no dashboard, so a page can render a single panel on
 * its own, the way a panel stands alone. Inside a dashboard, `ContentTile` passes the tile's actions.
 */
export function PanelCard({
    panel,
    panels,
    actions = [],
    editable = false,
    setConfig,
}: {
    panel: ContentPanel
    /** The panel types the page can show. The card renders the one that `panel.type` names. */
    panels: PanelDefinition[]
    /** What a person can do to the tile, shown on right-click. Left out, the card has no menu. */
    actions?: MenuAction[]
    /** Marks where the card is dragged by. */
    editable?: boolean
    /** Lets a panel that edits in place, such as text, save its config. Left out, the panel is read-only. */
    setConfig?: (config: unknown) => void
}): JSX.Element {
    const definition = findPanel(panels, panel.type)
    const slots = panelSlots(definition)
    const showHeader = isPartShown(panel, 'header', slots)
    const showFooter = isPartShown(panel, 'footer', slots)
    const look = cardLook(panel, definition?.appearance ?? {})
    const HeaderActions = definition?.HeaderActions
    const Footer = definition?.Footer
    const hasMenu = hasTileMenu(actions)

    return (
        <TileContextMenu actions={actions}>
            <Card
                size="sm"
                // A tile without a header has no title bar, so the whole tile is what it is dragged by.
                className={clsx('dash-PanelCard', look.className, editable && !showHeader && 'TileGrid__handle')}
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
                        {(HeaderActions || hasMenu) && (
                            <CardAction className="flex items-center gap-1">
                                {HeaderActions && <HeaderActions panel={panel} />}
                                {hasMenu && <TileMenuButton className="TileHoverReveal" />}
                            </CardAction>
                        )}
                    </CardHeader>
                )}
                {!showHeader && hasMenu && <TileMenuButton className="TileHoverReveal dash-PanelCard__float-toolbar" />}
                <CardContent className="flex flex-col flex-1 min-h-0 overflow-hidden">
                    <PanelView panel={panel} definition={definition} setConfig={setConfig} />
                </CardContent>
                {showFooter && (
                    // The grid's drag cancel selector lists this class, so a tile dragged by its body never starts a drag here.
                    <CardFooter className="dash-PanelCard__footer flex shrink-0 items-center gap-2 min-w-0 text-xs text-secondary">
                        {Footer ? <Footer panel={panel} /> : <UpdatedAt refreshedAt={panel.refreshedAt} />}
                    </CardFooter>
                )}
            </Card>
        </TileContextMenu>
    )
}
