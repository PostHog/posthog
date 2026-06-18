import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { range } from 'lib/utils/arrays'

export interface TableTileSkeletonProps {
    rows?: number
    numericColumns?: number
}

const LABEL_WIDTHS = ['w-40', 'w-32', 'w-44', 'w-28', 'w-36', 'w-40', 'w-24', 'w-32']

function rowLabelWidthClass(i: number): string {
    return LABEL_WIDTHS[i % LABEL_WIDTHS.length]
}

export function TableTileSkeleton({ rows = 8, numericColumns = 3 }: TableTileSkeletonProps): JSX.Element {
    return (
        <div data-attr="web-analytics-skeleton-table" className="flex flex-col flex-1">
            <div
                data-attr="web-analytics-skeleton-table-header"
                className="flex flex-row items-center justify-between border-b px-3 py-2 gap-4"
            >
                <LemonSkeleton className="h-3 w-24" />
                <div
                    data-attr="web-analytics-skeleton-table-header-numeric"
                    className="flex flex-row items-center gap-4"
                >
                    {range(numericColumns).map((i) => (
                        <LemonSkeleton key={i} className="h-3 w-12" />
                    ))}
                </div>
            </div>
            <div data-attr="web-analytics-skeleton-table-body" className="flex flex-col">
                {range(rows).map((i) => (
                    <div
                        key={i}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ opacity: 1 - i / (rows + 2) }}
                        className="flex flex-row items-center justify-between px-3 py-2 gap-4"
                    >
                        <LemonSkeleton className={`h-3 ${rowLabelWidthClass(i)}`} />
                        <div className="flex flex-row items-center gap-4">
                            {range(numericColumns).map((j) => (
                                <LemonSkeleton key={j} className="h-3 w-12" />
                            ))}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}
