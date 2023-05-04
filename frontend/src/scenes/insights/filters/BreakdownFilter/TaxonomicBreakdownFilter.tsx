import { BindLogic } from 'kea'
import { BreakdownFilter } from '~/queries/schema'
import { FilterType } from '~/types'

import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'
import { TaxonomicBreakdownTags } from './TaxonomicBreakdownTags'
import { TaxonomicBreakdownButton } from './TaxonomicBreakdownButton'
import './TaxonomicBreakdownFilter.scss'

export interface TaxonomicBreakdownFilterProps {
    filters: Partial<FilterType>
    setFilters?: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
    useMultiBreakdown?: boolean
}

export function TaxonomicBreakdownFilter({
    filters,
    setFilters,
    useMultiBreakdown = false,
}: TaxonomicBreakdownFilterProps): JSX.Element {
    const {
        breakdown,
        breakdowns,
        breakdown_type,
        breakdown_normalize_url,
        breakdown_value,
        breakdown_group_type_index,
        breakdown_histogram_bin_count,
    } = filters

    const breakdownFilter: BreakdownFilter = {
        breakdown_type,
        breakdown,
        breakdowns,
        breakdown_normalize_url,
        breakdown_value,
        breakdown_group_type_index,
        breakdown_histogram_bin_count,
    }

    return (
        <BindLogic logic={taxonomicBreakdownFilterLogic} props={{ breakdownFilter, setFilters, useMultiBreakdown }}>
            <div className="flex flex-wrap gap-2 items-center">
                {/* <TaxonomicBreakdownTags /> */}
                <TaxonomicBreakdownButton />
            </div>
        </BindLogic>
    )
}
