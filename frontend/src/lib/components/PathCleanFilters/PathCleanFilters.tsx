import '../../../scenes/actions/Actions.scss'
import { FilterRow } from '../PropertyFilters/components/FilterRow'
import { PathRegexPopup } from './PathRegexPopup'
import { PathCleaningFilter } from '~/types'

interface PathCleanFilterProps {
    pageKey: string
    pathCleaningFilters: PathCleaningFilter[]
    onChange: (newItem: PathCleaningFilter) => void
    onRemove: (index: number) => void
}

export function PathCleanFilters({
    pageKey,
    pathCleaningFilters,
    onChange,
    onRemove,
}: PathCleanFilterProps): JSX.Element {
    return (
        <div className="flex items-center gap-2 flex-wrap">
            {pathCleaningFilters.map((item, index) => (
                <FilterRow
                    key={index}
                    item={item}
                    index={index}
                    totalCount={pathCleaningFilters.length - 1} // empty state
                    filters={pathCleaningFilters}
                    pageKey={pageKey}
                    label="Add rule"
                    onRemove={onRemove}
                    filterComponent={(onComplete) => (
                        <PathRegexPopup
                            item={item}
                            onClose={onComplete}
                            onComplete={(newItem) => {
                                onChange(newItem)
                                onComplete()
                            }}
                        />
                    )}
                />
            ))}
        </div>
    )
}
