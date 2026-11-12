import { PreviewCard } from '@base-ui/react/preview-card'
import { ReactNode, Suspense } from 'react'

import { Card, Skeleton } from '@posthog/quill'

import { lazyWithRetry } from 'lib/utils/retryImport'

const TodayPulseInsightPreview = lazyWithRetry(() =>
    import('./TodayPulseInsightPreview').then(({ TodayPulseInsightPreview }) => ({
        default: TodayPulseInsightPreview,
    }))
)

export function TodayPulseInsightHover({ shortId, children }: { shortId: string; children: ReactNode }): JSX.Element {
    return (
        <PreviewCard.Root>
            <PreviewCard.Trigger delay={400} closeDelay={100} render={<div />}>
                {children}
            </PreviewCard.Trigger>
            <PreviewCard.Portal>
                <PreviewCard.Positioner
                    data-quill
                    data-quill-portal="popover"
                    className="[--quill-z-popover:var(--z-popover-with-chart)]"
                    side="left"
                    align="center"
                    sideOffset={10}
                >
                    <PreviewCard.Popup className="origin-[var(--transform-origin)] outline-none transition-[opacity,scale] duration-150 ease-out data-[ending-style]:scale-97 data-[ending-style]:opacity-0 data-[starting-style]:scale-97 data-[starting-style]:opacity-0 motion-reduce:transition-none">
                        <Card size="sm" className="w-64 gap-0 border border-border py-0 shadow-[var(--shadow-md)]">
                            <Suspense fallback={<Skeleton className="m-3 h-14" />}>
                                <TodayPulseInsightPreview shortId={shortId} />
                            </Suspense>
                        </Card>
                    </PreviewCard.Popup>
                </PreviewCard.Positioner>
            </PreviewCard.Portal>
        </PreviewCard.Root>
    )
}
