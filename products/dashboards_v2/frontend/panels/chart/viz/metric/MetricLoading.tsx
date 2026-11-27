import { Skeleton } from '@posthog/quill'

import { SkeletonSvg } from '../../ChartFrameSkeleton'

export function MetricLoading(): JSX.Element {
    return (
        <div className="flex min-h-0 flex-1 flex-col gap-2" aria-busy="true">
            <Skeleton className="h-8 w-24" />
            <SkeletonSvg viewBox="0 0 300 40" className="min-h-0 w-full flex-1">
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
            </SkeletonSvg>
        </div>
    )
}
