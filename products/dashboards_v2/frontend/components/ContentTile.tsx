import clsx from 'clsx'

import { IconTrash } from '@posthog/icons'
import { Button, Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@posthog/quill'

import type { ContentWidget } from '../layout/dashboardTypes'
import { WidgetView } from '../widgets/WidgetView'
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
    const actions = useContentTileActions(id)
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

    return (
        <TileContextMenu actions={actions}>
            <Card
                size="sm"
                // A tile without a title has no title bar, so the whole tile is what it is dragged by.
                className={clsx('DashboardV2__card', editable && !widget.title && 'DashboardV2__handle')}
            >
                {widget.title && (
                    <CardHeader className={clsx(editable && 'DashboardV2__handle')}>
                        <CardTitle className="truncate">{widget.title}</CardTitle>
                        {widget.description && (
                            <CardDescription className="truncate">{widget.description}</CardDescription>
                        )}
                        {editable && <CardAction className="DashboardV2__chrome">{removeButton}</CardAction>}
                    </CardHeader>
                )}
                {!widget.title && editable && (
                    <div className="DashboardV2__chrome DashboardV2__float-toolbar">{removeButton}</div>
                )}
                <CardContent className="flex flex-col flex-1 min-h-0 overflow-hidden">
                    <WidgetView widget={widget} />
                </CardContent>
            </Card>
        </TileContextMenu>
    )
}
