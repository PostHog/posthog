import clsx from 'clsx'

import { IconTrash } from '@posthog/icons'
import { Button, Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@posthog/quill'

import { type ContentWidget, showsPart } from '../layout/dashboardTypes'
import { WidgetView } from '../widgets/WidgetView'
import { ContentTileFooter } from './ContentTileFooter'
import { TileContextMenu, useContentTileActions } from './TileContextMenu'

export function ContentTile({
    id,
    widget,
    editable,
}: {
    id: string
    widget: ContentWidget
    editable: boolean
}): JSX.Element {
    const actions = useContentTileActions(id, widget)
    const remove = actions.find((action) => action.key === 'remove')
    const removeButton = remove && (
        <Button
            size="icon-xs"
            tooltip={remove.label}
            aria-label={remove.label}
            data-attr={remove.dataAttr}
            disabledReason={remove.disabledReason}
            onClick={remove.onSelect}
        >
            <IconTrash />
        </Button>
    )

    const showHeader = !!widget.title && showsPart(widget, 'header')
    const showDescription = !!widget.description && showsPart(widget, 'description')
    const footer = showsPart(widget, 'footer') ? widget.footer : undefined

    return (
        <TileContextMenu actions={actions}>
            <Card
                size="sm"
                // A tile without a header has no title bar, so the whole tile is what it is dragged by.
                className={clsx('DashboardV2__card', editable && !showHeader && 'DashboardV2__handle')}
            >
                {showHeader && (
                    <CardHeader className={clsx(editable && 'DashboardV2__handle')}>
                        <CardTitle className="truncate">{widget.title}</CardTitle>
                        {showDescription && (
                            <CardDescription className="truncate">{widget.description}</CardDescription>
                        )}
                        {editable && <CardAction className="DashboardV2__chrome">{removeButton}</CardAction>}
                    </CardHeader>
                )}
                {!showHeader && editable && (
                    <div className="DashboardV2__chrome DashboardV2__float-toolbar">{removeButton}</div>
                )}
                <CardContent className="flex flex-col flex-1 min-h-0 overflow-hidden">
                    <WidgetView widget={widget} />
                </CardContent>
                {footer?.length ? <ContentTileFooter items={footer} refreshedAt={widget.refreshedAt} /> : null}
            </Card>
        </TileContextMenu>
    )
}
