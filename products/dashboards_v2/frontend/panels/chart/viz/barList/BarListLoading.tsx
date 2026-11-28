import { Skeleton } from '@posthog/quill'

const BAR_WIDTHS = ['w-full', 'w-3/4', 'w-1/2', 'w-1/3', 'w-1/5']

export function BarListLoading(): JSX.Element {
    return (
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden" aria-busy="true">
            {BAR_WIDTHS.map((widthClass, index) => (
                <div key={index} className="flex items-center gap-3">
                    <Skeleton className="h-2 w-14 shrink-0" />
                    <div className="flex-1">
                        <Skeleton className={`h-2 ${widthClass}`} />
                    </div>
                    <Skeleton className="h-2 w-8 shrink-0" />
                </div>
            ))}
        </div>
    )
}
