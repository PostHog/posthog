import type { ReactNode } from 'react'

import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '@posthog/quill'

export function QuillInsightErrorLayout({
    illustration,
    title,
    detail,
    actions,
    footer,
}: {
    illustration: JSX.Element
    title: string | JSX.Element
    detail?: ReactNode
    actions?: ReactNode
    footer?: ReactNode
}): JSX.Element {
    // pinned: tests, stories and autocapture select on both data-attr values, so do not rename them
    return (
        <Empty data-attr="insight-empty-state" className="flex-1 min-h-0 border-none px-4 py-6">
            <EmptyHeader>
                {illustration}
                <EmptyTitle data-attr="insight-loading-too-long">{title}</EmptyTitle>
                <EmptyDescription className="flex flex-col items-center gap-1 *:mb-0 empty:hidden">
                    {detail}
                </EmptyDescription>
            </EmptyHeader>
            <EmptyContent className="flex-row flex-wrap justify-center empty:hidden">{actions}</EmptyContent>
            <div className="flex flex-col items-center gap-1 empty:hidden">{footer}</div>
        </Empty>
    )
}
