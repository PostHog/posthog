import type { ReactNode } from 'react'

import { TZLabel } from 'lib/components/TZLabel'

import { type ContentWidget, type FooterWidgetType, isFooterWidgetType } from '../layout/dashboardTypes'

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

/** What each widget type renders in its tile's footer. A type can put anything here; these are the defaults. */
const WIDGET_FOOTERS: Record<FooterWidgetType, (widget: ContentWidget) => ReactNode> = {
    stat: (widget) => <UpdatedAt refreshedAt={widget.refreshedAt} />,
    line: (widget) => <UpdatedAt refreshedAt={widget.refreshedAt} />,
    bar: (widget) => <UpdatedAt refreshedAt={widget.refreshedAt} />,
}

export function WidgetFooter({ widget }: { widget: ContentWidget }): JSX.Element | null {
    if (!isFooterWidgetType(widget.type)) {
        return null
    }
    return <>{WIDGET_FOOTERS[widget.type](widget)}</>
}
