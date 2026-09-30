import { ReactNode } from 'react'

import { MenuLabel } from '@posthog/quill'

/** A labelled run of rows inside a sidebar pane, such as one day of sessions or one tool category. */
export function TodayPaneGroup({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <div role="group" aria-label={label} className="flex flex-col gap-px">
            <MenuLabel aria-hidden>{label}</MenuLabel>
            {children}
        </div>
    )
}
