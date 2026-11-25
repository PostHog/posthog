import './WidgetCard.css'
import './TileHoverReveal.css'

import clsx from 'clsx'

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

import type { ContentWidget } from '../dashboard/dashboardTypes'
import type { MenuAction } from '../dashboard/menuAction'
import { showsBackground, showsBorder } from '../presentation/tileAppearance'
import { isPartShown } from '../presentation/tileParts'
import { type WidgetDefinition, widgetSlots } from '../widgets/widgetDefinition'
import { findWidget } from '../widgets/widgetSpec'
import { WidgetView } from '../widgets/WidgetView'
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

/**
 * One widget in its card: header, body and footer. It reads no dashboard, so a page can render a single widget on
 * its own, the way a panel stands alone. Inside a dashboard, `ContentTile` passes the tile's actions.
 */
export function WidgetCard({
    widget,
    widgets,
    actions = [],
    editable = false,
}: {
    widget: ContentWidget
    /** The widget types the page can show. The card renders the one that `widget.type` names. */
    widgets: WidgetDefinition[]
    /** What a person can do to the tile, shown on right-click. Left out, the card has no menu. */
    actions?: MenuAction[]
    /** Marks where the card is dragged by. */
    editable?: boolean
}): JSX.Element {
    const definition = findWidget(widgets, widget.type)
    const slots = widgetSlots(definition)
    const showHeader = isPartShown(widget, 'header', slots)
    const showFooter = isPartShown(widget, 'footer', slots)
    const showBackground = showsBackground(widget, definition?.appearance ?? {})
    const HeaderActions = definition?.HeaderActions
    const Footer = definition?.Footer
    const hasMenu = hasTileMenu(actions)

    return (
        <TileContextMenu actions={actions}>
            <Card
                size="sm"
                // A tile without a header has no title bar, so the whole tile is what it is dragged by.
                className={clsx(
                    'dash-WidgetCard',
                    !showBackground && 'dash-WidgetCard--no-background',
                    !showsBorder(widget) && 'dash-WidgetCard--no-border',
                    editable && !showHeader && 'TileGrid__handle'
                )}
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
                        {(HeaderActions || hasMenu) && (
                            <CardAction className="flex items-center gap-1">
                                {HeaderActions && <HeaderActions widget={widget} />}
                                {hasMenu && <TileMenuButton className="TileHoverReveal" />}
                            </CardAction>
                        )}
                    </CardHeader>
                )}
                {!showHeader && hasMenu && (
                    <TileMenuButton className="TileHoverReveal dash-WidgetCard__float-toolbar" />
                )}
                <CardContent className="flex flex-col flex-1 min-h-0 overflow-hidden">
                    <WidgetView widget={widget} definition={definition} />
                </CardContent>
                {showFooter && (
                    // The grid's drag cancel selector lists this class, so a tile dragged by its body never starts a drag here.
                    <CardFooter className="dash-WidgetCard__footer flex shrink-0 items-center gap-2 min-w-0 text-xs text-secondary">
                        {Footer ? <Footer widget={widget} /> : <UpdatedAt refreshedAt={widget.refreshedAt} />}
                    </CardFooter>
                )}
            </Card>
        </TileContextMenu>
    )
}
