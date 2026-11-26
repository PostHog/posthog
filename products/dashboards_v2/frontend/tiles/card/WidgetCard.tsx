import './WidgetCard.css'

import clsx from 'clsx'
import type { CSSProperties } from 'react'

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

import type { SavedWidget } from '../../dashboard/document/dashboardTypes'
import type { MenuAction } from '../../menu/menuAction'
import { NO_BACKGROUND, showsBorder, tileBackgroundColor } from '../../presentation/tileAppearance'
import { isPartShown } from '../../presentation/tileParts'
import { type WidgetType, widgetSlots } from '../../widgets/widgetDefinition'
import { WidgetErrorBoundary } from '../../widgets/WidgetErrorBoundary'
import { type WidgetAppearanceOptions, findWidget } from '../../widgets/widgetSpec'
import { WidgetView } from '../../widgets/WidgetView'
import { TileActions } from '../menu/TileActions'
import { TileContextMenu, hasTileMenu } from '../menu/TileContextMenu'

function cardLook(
    widget: SavedWidget,
    options: WidgetAppearanceOptions
): { className: string; style: CSSProperties | undefined } {
    const color = tileBackgroundColor(widget, options)
    const tint = color === NO_BACKGROUND ? null : color
    return {
        className: clsx(
            color === NO_BACKGROUND && 'dash-WidgetCard--no-background',
            !showsBorder(widget) && 'dash-WidgetCard--no-border',
            tint && 'dash-WidgetCard--tinted'
        ),
        // A saved color can be any CSS color, so no class can carry it.
        style: tint ? ({ '--dv2-tile-background-color': tint } as CSSProperties) : undefined,
    }
}

/**
 * One widget in its card: header, body and footer. It reads no dashboard, so a page can render a single widget on
 * its own, the way a panel stands alone. Inside a dashboard, `ContentTile` passes the tile's actions.
 */
export function WidgetCard({
    widget,
    widgets,
    actions = [],
    editable = false,
    setConfig,
}: {
    widget: SavedWidget
    /** The widget types the page can show. The card renders the one that `widget.type` names. */
    widgets: WidgetType[]
    /** What a person can do to the tile, shown on right-click. Left out, the card has no menu. */
    actions?: MenuAction[]
    editable?: boolean
    /** Lets a widget that edits in place, such as text, save its config. Left out, the widget is read-only. */
    setConfig?: (config: unknown) => void
}): JSX.Element {
    const definition = findWidget(widgets, widget.type)
    const slots = widgetSlots(definition)
    const showHeader = isPartShown(widget, 'header', slots)
    const showFooter = isPartShown(widget, 'footer', slots)
    const look = cardLook(widget, definition?.appearance ?? {})
    const HeaderExtra = definition?.HeaderExtra
    const Footer = definition?.Footer
    const hasMenu = hasTileMenu(actions)

    return (
        <TileContextMenu actions={actions}>
            <Card
                size="sm"
                // A tile without a header has no title bar, so the whole tile is what it is dragged by.
                className={clsx('dash-WidgetCard', look.className, editable && !showHeader && 'TileGrid__handle')}
                style={look.style}
            >
                {showHeader && (
                    <CardHeader className={clsx(editable && 'TileGrid__handle')}>
                        <CardTitle className="flex items-center gap-1 min-w-0">
                            <span className="TileGrid__text truncate">{widget.title}</span>
                            {widget.description && (
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <span
                                                tabIndex={0}
                                                className="inline-flex shrink-0 text-muted-foreground"
                                                aria-label={widget.description}
                                            />
                                        }
                                    >
                                        <IconInfo />
                                    </TooltipTrigger>
                                    <TooltipContent className="max-w-80">{widget.description}</TooltipContent>
                                </Tooltip>
                            )}
                        </CardTitle>
                        {(HeaderExtra || hasMenu) && (
                            <TileActions menu={hasMenu}>
                                {HeaderExtra && (
                                    <WidgetErrorBoundary widget={widget} fallback={null}>
                                        <HeaderExtra widget={widget} />
                                    </WidgetErrorBoundary>
                                )}
                            </TileActions>
                        )}
                    </CardHeader>
                )}
                {!showHeader && hasMenu && <TileActions menu className="dash-WidgetCard__float-toolbar" />}
                <CardContent className="flex flex-col flex-1 min-h-0 overflow-hidden">
                    <WidgetView widget={widget} definition={definition} setConfig={setConfig} />
                </CardContent>
                {showFooter && (
                    // The grid's drag cancel selector lists this class, so a tile dragged by its body never starts a drag here.
                    <CardFooter className="dash-WidgetCard__footer flex shrink-0 items-center gap-2 min-w-0 text-xs text-secondary">
                        {Footer && (
                            <WidgetErrorBoundary widget={widget} fallback={null}>
                                <Footer widget={widget} />
                            </WidgetErrorBoundary>
                        )}
                    </CardFooter>
                )}
            </Card>
        </TileContextMenu>
    )
}
