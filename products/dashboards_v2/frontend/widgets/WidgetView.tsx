import { memo } from 'react'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { ContentWidget } from '../layout/dashboardTypes'

const PLACEHOLDER_LABEL: Record<ContentWidget['type'], string> = {
    stat: 'Number',
    line: 'Line chart',
    bar: 'Bar chart',
    markdown: 'Text',
}

/** Memoised on the widget, which keeps its identity through every layout edit, so moving tiles never re-renders it. */
export const WidgetView = memo(function WidgetView({ widget }: { widget: ContentWidget }): JSX.Element {
    if (widget.type === 'markdown') {
        return <LemonMarkdown className="text-sm">{widget.text ?? ''}</LemonMarkdown>
    }
    return (
        <div className="flex h-full items-center justify-center text-secondary text-sm">
            {PLACEHOLDER_LABEL[widget.type]}
        </div>
    )
})
