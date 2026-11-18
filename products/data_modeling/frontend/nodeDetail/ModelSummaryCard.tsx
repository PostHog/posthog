import type { ReactNode } from 'react'

import { LemonCard } from '@posthog/lemon-ui'

export function ModelSummaryCard({
    children,
    metadata,
    dataAttr,
}: {
    children: ReactNode
    metadata?: ReactNode
    dataAttr: string
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="!p-4 w-full @container/model-summary" data-attr={dataAttr}>
            <div className="flex flex-col gap-4 @3xl/model-summary:flex-row @3xl/model-summary:gap-8">
                <div className="min-w-0 flex-1">{children}</div>
                {metadata && (
                    <div className="min-w-0 border-t pt-4 @3xl/model-summary:w-80 @3xl/model-summary:shrink-0 @3xl/model-summary:border-t-0 @3xl/model-summary:border-l @3xl/model-summary:pt-0 @3xl/model-summary:pl-8">
                        {metadata}
                    </div>
                )}
            </div>
        </LemonCard>
    )
}
