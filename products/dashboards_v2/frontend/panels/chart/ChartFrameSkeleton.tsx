import type { ReactNode } from 'react'

import { Skeleton } from '@posthog/quill'

const GRID_LINES = 4

export function ChartFrameSkeleton({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div className="flex min-h-0 flex-1 flex-col gap-2" aria-busy="true">
            <div className="flex min-h-0 flex-1 gap-2">
                <div className="flex flex-col justify-between py-0.5">
                    {Array.from({ length: GRID_LINES }, (_, index) => (
                        <Skeleton key={index} className="h-2 w-6" />
                    ))}
                </div>
                <div className="relative min-h-0 flex-1">
                    <div className="absolute inset-0 flex flex-col justify-between py-1.5">
                        {Array.from({ length: GRID_LINES }, (_, index) => (
                            <div key={index} className="border-t border-dashed border-primary" />
                        ))}
                    </div>
                    <div className="absolute inset-0 flex items-end gap-1.5 pb-1.5">{children}</div>
                </div>
            </div>
            <div className="flex justify-between gap-3 pl-8">
                {Array.from({ length: 5 }, (_, index) => (
                    <Skeleton key={index} className="h-2 w-10" />
                ))}
            </div>
        </div>
    )
}
