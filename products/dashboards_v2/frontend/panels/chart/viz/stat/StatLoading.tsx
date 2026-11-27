import { Skeleton } from '@posthog/quill'

export function StatLoading(): JSX.Element {
    return (
        <div className="flex min-h-0 flex-1 flex-col gap-2" aria-busy="true">
            <Skeleton className="h-8 w-24" />
            <svg
                viewBox="0 0 300 40"
                preserveAspectRatio="none"
                className="min-h-0 w-full flex-1 animate-pulse text-primary opacity-15 motion-reduce:animate-none"
                aria-hidden="true"
            >
                <path
                    d="M0 32 C40 30 70 24 110 27 S170 18 210 22 S260 12 300 14 V40 H0 Z"
                    fill="currentColor"
                    opacity="0.4"
                />
                <path
                    d="M0 32 C40 30 70 24 110 27 S170 18 210 22 S260 12 300 14"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    vectorEffect="non-scaling-stroke"
                />
            </svg>
        </div>
    )
}
