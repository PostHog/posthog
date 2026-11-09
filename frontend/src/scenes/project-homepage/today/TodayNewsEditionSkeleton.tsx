import { Skeleton } from '@posthog/quill'

import { TodayNewsColumns } from './TodayNewsColumns'

const STORY_TITLE_WIDTHS = ['w-3/4', 'w-2/3', 'w-4/5']

export function TodayNewsEditionSkeleton(): JSX.Element {
    return (
        <div className="@container flex flex-col">
            <div className="grid gap-6 px-4 py-6 @3xl:grid-cols-2">
                <span className="flex flex-col gap-2">
                    <Skeleton className="h-3 w-24" />
                    <Skeleton className="h-7 w-11/12" />
                    <Skeleton className="h-7 w-2/3" />
                    <Skeleton className="h-4 w-4/5" />
                </span>
                <Skeleton className="h-36" />
            </div>
            <div className="border-t">
                <TodayNewsColumns count={STORY_TITLE_WIDTHS.length}>
                    {STORY_TITLE_WIDTHS.map((width) => (
                        <li key={width} className="flex flex-col gap-2">
                            <Skeleton className="h-3 w-20" />
                            <Skeleton className={`h-5 ${width}`} />
                            <Skeleton className="h-4 w-full" />
                        </li>
                    ))}
                </TodayNewsColumns>
            </div>
        </div>
    )
}
