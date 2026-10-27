import { Skeleton, cn } from '@posthog/quill'

const ROW_WIDTHS = ['w-3/5', 'w-4/5', 'w-1/2', 'w-2/3'] as const

export function BetsSidebarSkeleton(): JSX.Element {
    return (
        <div
            role="status"
            aria-label="Loading bets"
            className="flex flex-col gap-px animate-fade-in [animation-delay:200ms] [animation-fill-mode:both] motion-reduce:animate-none"
        >
            {ROW_WIDTHS.map((width) => (
                <div key={width} aria-hidden className="flex h-7 items-center gap-1.5 px-2">
                    <span className="flex size-3.5 shrink-0 items-center justify-center">
                        <Skeleton className="size-2 rounded-full" />
                    </span>
                    <Skeleton className={cn('h-2.5 rounded-full', width)} />
                </div>
            ))}
        </div>
    )
}
