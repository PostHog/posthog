import clsx from 'clsx'
import { useActions } from 'kea'

import { IconTrash } from '@posthog/icons'
import { Button, Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@posthog/quill'

import { dashboardV2Logic } from '../dashboardV2Logic'
import type { ContentWidget } from '../layout/dashboardTypes'
import { WidgetView } from '../widgets/WidgetView'

export function ContentTile({
    id,
    widget,
    editable,
}: {
    id: string
    widget: ContentWidget
    editable: boolean
}): JSX.Element {
    const { applyDashboardEdit } = useActions(dashboardV2Logic)
    const removeButton = (
        <Button
            size="icon-xs"
            tooltip="Remove tile"
            aria-label="Remove tile"
            data-attr="dashboard-v2-tile-remove"
            onClick={() => applyDashboardEdit({ edit: 'removeTile', id })}
        >
            <IconTrash />
        </Button>
    )

    return (
        <Card
            size="sm"
            // A tile without a title has no title bar, so the whole tile is what it is dragged by.
            className={clsx('DashboardV2__card', editable && !widget.title && 'DashboardV2__handle')}
        >
            {widget.title && (
                <CardHeader className={clsx(editable && 'DashboardV2__handle')}>
                    <CardTitle className="truncate">{widget.title}</CardTitle>
                    {widget.description && <CardDescription className="truncate">{widget.description}</CardDescription>}
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
    )
}
