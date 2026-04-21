import { LemonSkeleton } from '@posthog/lemon-ui'

const TABLE_COLUMN_COUNT = 10

export function SubscriptionsLoadingSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-4 max-w-full w-full">
            <div className="flex justify-between gap-2 flex-wrap items-center">
                <div className="flex-1 min-w-0 max-w-3xl">
                    <LemonSkeleton className="h-10 w-full rounded" />
                </div>
                <div className="flex items-center gap-2">
                    <LemonSkeleton className="h-4 w-20" />
                    <LemonSkeleton className="h-10 w-44" />
                </div>
            </div>
            <div className="border rounded bg-primary overflow-hidden">
                <div className="flex gap-3 px-3 py-2 border-b border-primary">
                    {Array.from({ length: TABLE_COLUMN_COUNT }).map((_, i) => (
                        <LemonSkeleton
                            key={`h-${i}`}
                            className={i === TABLE_COLUMN_COUNT - 1 ? 'h-4 w-8 shrink-0' : 'h-4 flex-1 min-w-[2.5rem]'}
                        />
                    ))}
                </div>
                {Array.from({ length: 8 }).map((_, row) => (
                    <div
                        key={row}
                        className="flex gap-3 px-3 py-2.5 border-b border-primary last:border-b-0 items-center"
                    >
                        {Array.from({ length: TABLE_COLUMN_COUNT }).map((_, col) => (
                            <LemonSkeleton
                                key={col}
                                className={
                                    col === TABLE_COLUMN_COUNT - 1
                                        ? 'h-8 w-8 shrink-0 rounded'
                                        : 'h-4 flex-1 min-w-[2.5rem]'
                                }
                            />
                        ))}
                    </div>
                ))}
            </div>
        </div>
    )
}
