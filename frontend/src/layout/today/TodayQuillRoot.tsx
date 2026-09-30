import { ReactNode } from 'react'

import { TooltipProvider } from '@posthog/quill'

/** The boundary of a quill subtree under the Today layout: scoped tokens, plus the tooltip provider quill expects. */
export function TodayQuillRoot({ className, children }: { className?: string; children: ReactNode }): JSX.Element {
    return (
        <TooltipProvider>
            <div data-quill className={className}>
                {children}
            </div>
        </TooltipProvider>
    )
}
