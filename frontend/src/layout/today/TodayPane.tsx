import { ReactNode } from 'react'

import { ScrollArea } from '@posthog/quill'

interface TodayPaneProps {
    /** The name of the navigation list, for screen readers. */
    label: string
    /** Stays above the list while it scrolls: a create button or a search field. */
    header?: ReactNode
    children: ReactNode
}

/** The body of one sidebar pane: an optional fixed header, then a scrolling navigation list. */
export function TodayPane({ label, header, children }: TodayPaneProps): JSX.Element {
    return (
        <div className="flex h-full min-h-0 flex-col gap-2 pt-4">
            {header && <div className="flex flex-col gap-2 px-3">{header}</div>}
            <ScrollArea className="min-h-0 flex-1" viewportClassName="px-3 pb-6">
                <nav aria-label={label} className="flex flex-col gap-3">
                    {children}
                </nav>
            </ScrollArea>
        </div>
    )
}
