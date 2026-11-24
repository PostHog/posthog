import { memo } from 'react'

import type { ContentWidget } from '../dashboard/dashboardTypes'
import type { WidgetDefinition } from './widgetDefinition'

/**
 * Memoised on the widget and its definition, which both keep their identity through every layout edit, so moving
 * tiles never re-renders it.
 */
export const WidgetView = memo(function WidgetView({
    widget,
    definition,
}: {
    widget: ContentWidget
    definition: WidgetDefinition | undefined
}): JSX.Element {
    if (!definition) {
        return (
            <div className="flex h-full items-center justify-center text-secondary text-sm">
                This dashboard can't show this widget type.
            </div>
        )
    }
    return <definition.Component widget={widget} />
})
