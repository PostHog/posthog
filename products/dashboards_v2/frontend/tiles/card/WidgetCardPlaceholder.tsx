import clsx from 'clsx'

import { Card, CardContent, CardHeader, CardTitle } from '@posthog/quill'

import type { SavedWidget } from '../../dashboard/document/dashboardTypes'
import { isPartShown } from '../../presentation/tileParts'
import { type WidgetType, widgetSlots } from '../../widgets/core/widgetDefinition'
import { WidgetErrorBoundary } from '../../widgets/core/WidgetErrorBoundary'
import { WidgetLoading } from '../../widgets/core/WidgetView'

/**
 * What a tile shows before its card mounts: the card's header and the widget type's loading state, so a tile that
 * scrolls into view already looks like itself. It reads no dashboard state, so off-screen tiles stay cheap.
 */
export function WidgetCardPlaceholder({
    widget,
    definition,
    editable,
}: {
    widget: SavedWidget
    definition: WidgetType | undefined
    editable: boolean
}): JSX.Element {
    const showHeader = isPartShown(widget, 'header', widgetSlots(definition))
    const Loading = definition?.Loading ?? WidgetLoading
    return (
        <Card size="sm" className={clsx('dash-WidgetCard', editable && !showHeader && 'TileGrid__handle')} aria-busy>
            {showHeader && (
                <CardHeader className={clsx(editable && 'TileGrid__handle')}>
                    <CardTitle className="TileGrid__text truncate">{widget.title}</CardTitle>
                </CardHeader>
            )}
            <CardContent className="flex flex-col flex-1 min-h-0 overflow-hidden">
                <WidgetErrorBoundary widget={widget} fallback={<WidgetLoading />}>
                    <Loading widget={widget} />
                </WidgetErrorBoundary>
            </CardContent>
        </Card>
    )
}
