import '../../../scenes/actions/Actions.scss'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FilterRow } from '../PropertyFilters/components/FilterRow'
import { PathRegexPopup } from './PathCleanFilter'
import { PathCleaningFilter } from '~/types'

interface PropertyFiltersProps {
    endpoint?: string | null
    onChange: (newItem: PathCleaningFilter) => void
    onRemove: (index: number) => void
    pathCleaningFilters: PathCleaningFilter[]
    pageKey: string
    showConditionBadge?: boolean
    disablePopover?: boolean
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
}

export function PathCleanFilters({
    pageKey,
    onChange,
    onRemove,
    pathCleaningFilters,
    showConditionBadge = false,
    disablePopover = false, // use bare PropertyFilter without popover
}: PropertyFiltersProps): JSX.Element {
    return (
        <div className="flex items-center gap-2 flex-wrap">
            {pathCleaningFilters.length > 0 &&
                pathCleaningFilters.map((item, index) => {
                    return (
                        <FilterRow
                            key={index}
                            item={item}
                            index={index}
                            totalCount={pathCleaningFilters.length - 1} // empty state
                            filters={pathCleaningFilters}
                            pageKey={pageKey}
                            showConditionBadge={showConditionBadge}
                            disablePopover={disablePopover}
                            label="Add rule"
                            onRemove={onRemove}
                            filterComponent={(onComplete) => {
                                return (
                                    <PathRegexPopup
                                        item={item}
                                        onClose={onComplete}
                                        onComplete={(newItem) => {
                                            onChange(newItem)
                                            onComplete()
                                        }}
                                    />
                                )
                            }}
                        />
                    )
                })}
        </div>
    )
}
