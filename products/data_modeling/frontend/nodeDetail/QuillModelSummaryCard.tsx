import type { ReactNode } from 'react'

import { Card, CardContent } from '@posthog/quill'

export function QuillModelSummaryCard({
    children,
    metadata,
    dataAttr,
}: {
    children: ReactNode
    metadata?: ReactNode
    dataAttr: string
}): JSX.Element {
    return (
        <Card size="sm" className="@container/model-summary w-full" data-attr={dataAttr}>
            <CardContent className="flex flex-col gap-4 @3xl/model-summary:flex-row @3xl/model-summary:gap-8">
                <div className="flex min-w-0 flex-1 flex-col gap-3">{children}</div>
                {metadata && (
                    <div className="min-w-0 border-t border-border pt-4 @3xl/model-summary:w-80 @3xl/model-summary:shrink-0 @3xl/model-summary:border-t-0 @3xl/model-summary:border-l @3xl/model-summary:pt-0 @3xl/model-summary:pl-8">
                        {metadata}
                    </div>
                )}
            </CardContent>
        </Card>
    )
}
