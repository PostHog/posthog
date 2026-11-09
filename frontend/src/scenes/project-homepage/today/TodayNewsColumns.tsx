import type { ReactNode } from 'react'

import { cn } from '@posthog/quill'

export function TodayNewsColumns({ count, children }: { count: number; children: ReactNode }): JSX.Element {
    return (
        <ul
            className={cn(
                'm-0 grid list-none p-0 [&>li]:px-4 [&>li]:py-6 [&>li+li]:border-t @3xl:[&>li+li]:border-t-0 @3xl:[&>li+li]:border-s @3xl:[&>li:not(:first-child)]:ps-6 @3xl:[&>li:not(:last-child)]:pe-6',
                count >= 3
                    ? '@3xl:grid-cols-3'
                    : count === 2
                      ? '@3xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]'
                      : undefined
            )}
        >
            {children}
        </ul>
    )
}
