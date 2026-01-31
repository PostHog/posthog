import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { pluralize } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

export interface FilteredTableCountProps {
    filtersChanged: boolean
    effectiveCount: number
    page: number
    pageSize: number
    noun: string
}

export function FilteredTableCount({
    filtersChanged,
    effectiveCount,
    page,
    pageSize,
    noun,
}: FilteredTableCountProps): JSX.Element | null {
    const startCount = effectiveCount === 0 ? 0 : (page - 1) * pageSize + 1
    const endCount = page * pageSize < effectiveCount ? page * pageSize : effectiveCount
    const countText = `${startCount}${endCount - startCount > 1 ? '-' + endCount : ''} of ${pluralize(effectiveCount, noun)}`

    return (
        <div>
            <span className={cn('text-secondary transition-opacity', filtersChanged && 'opacity-50')}>
                {filtersChanged ? (
                    <WrappingLoadingSkeleton>{countText}</WrappingLoadingSkeleton>
                ) : effectiveCount > 0 ? (
                    countText
                ) : null}
            </span>
        </div>
    )
}
